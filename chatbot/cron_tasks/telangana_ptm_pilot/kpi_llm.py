import hashlib
import json
import logging
import traceback

from chatbot.llm_models.llm_script import handle_bedrock_model

logger = logging.getLogger('django')

BOT_ROUTE = '/telangana-ptm-metrics'
LLM_BATCH_SIZE = 25


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()


def _dedup(items: list) -> tuple:
    """
    items: list of (session_id, field, text)
    Returns (unique_items, hash_to_sessions)
    hash_to_sessions: {(field, sha1): [session_id, ...]}
    """
    seen = {}
    unique = []
    hash_to_sessions = {}

    for session_id, field, text in items:
        key = (field, _sha1(text))
        if key not in seen:
            seen[key] = len(unique)
            unique.append((session_id, field, text))
        hash_to_sessions.setdefault(key, []).append(session_id)

    return unique, hash_to_sessions


def _build_messages(batch: list) -> list:
    payload = [{'id': s, 'field': f, 'text': t} for s, f, t in batch]
    return [
        {'role': 'user', 'content': [{'text': json.dumps(payload)}]},
    ]


def _parse_response(response) -> dict:
    try:
        results = response.get('results', [])
        return {str(item['id']): {item['field']: {k: v for k, v in item.items() if k not in ('id', 'field')}}
                for item in results if 'id' in item and 'field' in item}
    except Exception:
        logger.warning('Failed to parse LLM response: %s', response)
        return {}


def llm_classify_batch(items: list, company_bot) -> dict:
    """
    items: list of (session_id, field, text)
    Returns {session_id: {field: label_dict}}
    """
    if not items:
        return {}

    unique, hash_to_sessions = _dedup(items)
    output = {}

    for i in range(0, len(unique), LLM_BATCH_SIZE):
        batch = unique[i:i + LLM_BATCH_SIZE]
        messages = _build_messages(batch)
        try:
            response = handle_bedrock_model(
                company_bot=company_bot,
                system_prompt=[{'text': company_bot.context}],
                messages=messages,
                model_name=company_bot.llm_model,
                temperature=company_bot.bot_temperature,
                max_token=company_bot.max_token,
            )
            parsed = _parse_response(response)
        except Exception:
            logger.error('LLM batch %d-%d failed:\n%s', i, i + LLM_BATCH_SIZE, traceback.format_exc())
            parsed = {}

        # Fan-out deduped results to all sessions sharing same (field, text)
        for rep_session_id, field, text in batch:
            key = (field, _sha1(text))
            field_result = parsed.get(str(rep_session_id), {}).get(field)
            if field_result is None:
                continue
            for sid in hash_to_sessions.get(key, [rep_session_id]):
                output.setdefault(str(sid), {})[field] = field_result

    return output
