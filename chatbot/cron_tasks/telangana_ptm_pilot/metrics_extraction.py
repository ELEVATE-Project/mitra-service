import logging
from collections import defaultdict
from datetime import timedelta

from django.db.models import Exists, OuterRef
from django.utils import timezone

from chatbot.models import CompanyChat, ChatSession
from chatbot.models.company_models import CompanyBot
from chatbot.models.story_models import Story
from chatbot.cron_tasks.telangana_ptm_pilot.kpi_rules import (
    load_keywords,
    classify_sentiment,
    STAGE_CLASSIFIERS,
    CONFIDENCE_THRESHOLD,
)
from chatbot.cron_tasks.telangana_ptm_pilot.kpi_llm import llm_classify_batch

logger = logging.getLogger('django')


def load_sessions_for_metrics() -> list:
    one_hour_ago = timezone.now() - timedelta(hours=1)
    recent_story = Story.objects.filter(
        session=OuterRef('session'),
        created_at__gte=one_hour_ago,
    )
    return list(
        ChatSession.objects
        .filter(session_type='telangana-ptm-pilot')
        .exclude(Exists(recent_story))
        .values_list('session', flat=True)
    )


def _build_session_chat_map(sessions: list) -> dict:
    chats = (
        CompanyChat.objects
        .filter(session__in=sessions)
        .order_by('created_at')
        .values('session', 'sender_id', 'stage', 'message', 'translated_message')
    )
    result = defaultdict(list)
    for chat in chats:
        result[chat['session']].append(chat)
    return dict(result)


def _effective_text(chat: dict) -> str:
    return chat['translated_message'] or chat['message'] or ''


def _extract_kpi_for_session(session_id: str, chats: list, keywords: dict) -> tuple:
    """
    Returns (rule_metrics: dict, llm_queue: list of (session_id, field, text))
    """
    rule_metrics = {}
    llm_queue = []

    # Sentiment: concat all user messages
    user_texts = [_effective_text(c) for c in chats if c['sender_id'] != 1]
    transcript = ' '.join(user_texts).strip()

    if transcript:
        label, conf = classify_sentiment(transcript, keywords)
        if label is not None and conf >= CONFIDENCE_THRESHOLD:
            rule_metrics['sentiment'] = label
        else:
            llm_queue.append((session_id, 'sentiment', transcript))

    # Stage KPIs: last user message per stage
    stage_texts = {}
    for chat in chats:
        if chat['sender_id'] != 1 and chat['stage'] in STAGE_CLASSIFIERS:
            stage_texts[chat['stage']] = _effective_text(chat)

    for stage, text in stage_texts.items():
        field_name, classifier_fn = STAGE_CLASSIFIERS[stage]
        if not text:
            continue
        label, conf = classifier_fn(text, keywords)
        if label is not None and conf >= CONFIDENCE_THRESHOLD:
            rule_metrics[field_name] = label
        else:
            llm_queue.append((session_id, field_name, text))

    return rule_metrics, llm_queue


def _merge_metrics_into_story(session_id: str, new_metrics: dict) -> None:
    story = Story.objects.filter(session=session_id).first()
    if not story:
        logger.info('No Story for session=%s, skipping', session_id)
        return
    story.other_params = {**(story.other_params or {}), **new_metrics}
    story.save(update_fields=['other_params', 'updated_at'])


def extract_metrics():
    try:
        company_bot = CompanyBot.objects.get(route='/telangana-ptm-metrics')
    except CompanyBot.DoesNotExist:
        logger.error('CompanyBot with route=/telangana-ptm-metrics not found. Create it in admin first.')
        return

    keywords = load_keywords(company_bot.dynamic_context)

    sessions = load_sessions_for_metrics()
    if not sessions:
        logger.info('No sessions to process for KPI metrics extraction.')
        return

    logger.info('Processing %d sessions for KPI metrics', len(sessions))
    chat_map = _build_session_chat_map(sessions)

    all_rule_metrics = {}
    all_llm_queue = []

    for session_id in sessions:
        chats = chat_map.get(session_id, [])
        rule_metrics, llm_queue = _extract_kpi_for_session(session_id, chats, keywords)
        all_rule_metrics[session_id] = rule_metrics

        # Save rule-classified fields immediately — no need to wait for LLM
        if rule_metrics:
            _merge_metrics_into_story(session_id, rule_metrics)

        all_llm_queue.extend(llm_queue)

    if all_llm_queue:
        logger.info('Sending %d items to LLM for KPI classification', len(all_llm_queue))
        llm_results = llm_classify_batch(all_llm_queue, company_bot)

        # Merge LLM results per session as they arrive; rule metrics already saved, so rule wins
        for session_id, field_results in llm_results.items():
            rule_fields = set(all_rule_metrics.get(session_id, {}).keys())
            llm_only = {f: v for f, v in field_results.items() if f not in rule_fields}
            if llm_only:
                _merge_metrics_into_story(session_id, llm_only)

    logger.info('KPI metrics extraction complete.')
