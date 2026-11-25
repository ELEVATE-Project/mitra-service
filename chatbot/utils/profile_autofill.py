"""
Profile auto-fill for state-machine steps (login feature).

A CompanyStateMachine step can be marked `is_linked_to_profile = True` with a `profile_key`
(e.g. "state", "district", "name"). When a logged-in user reaches such a step and their profile
has a value for that key, the bot does not ask the question: the profile value is saved as the
user's answer, exactly like a typed answer, and the conversation moves on to the next step.

A question that asks for several things at once (e.g. "...the village, block, district and state...")
can list several comma-separated keys: `village,block,district,state`. It is auto-filled only when the
profile has a value for every key, as "Rampur, Hosakote, Bangalore, Karnataka" (values in the
configured order); if any one is missing the question is asked, so a partial answer is never saved.

Rules (see .claude/work/login/profile-autofill-plan.md, D1-D3 / A1-A5):
  - The configured key(s) are used as-is; they are never matched against the question text.
  - Guests, or users whose profile has no usable value for the key, are asked the question as usual.
  - Several linked steps in a row are all answered in one go.
  - The answer is saved in the profile's own wording (`message`), with `translated_message = NULL`,
    whatever the chat language is. The LLM falls back to `message` when `translated_message` is empty.
  - Nothing in here may break the chat: any unexpected error is logged and treated as
    "nothing auto-filled", so the bot simply asks the question.

Shared by both step-advance paths:
  - non_llm: chatbot/views/chat_view.py -> non_llm_chat_view
  - llm:     CommonResponseHandler._handle_function_call (Stage 3)
"""
import logging

from chatbot.models import ChatStatus, CompanyChat
from chatbot.models.company_models import CompanyStateMachine
from chatbot.models.enums import ValidationTypeChoices
from chatbot.utils.chat_utils import get_ai_profile

logger = logging.getLogger("django")

# Fields needed to decide whether a step can be auto-filled and to save its question row.
# Kept small on purpose: the query below loads every remaining step of the bot in one go.
_STEP_FIELDS = (
    "step", "name", "bot_question", "translations",
    "is_linked_to_profile", "profile_key", "validation_type", "validation_config",
)


def _get(state_machine, field):
    """Read a field from either a CompanyStateMachine instance or a `.values()` dict."""
    if isinstance(state_machine, dict):
        return state_machine.get(field)
    return getattr(state_machine, field, None)


def parse_profile_keys(raw_profile_key):
    """
    Split a configured profile_key into a clean list of keys, in the configured order.

    "village, block ,district,,state " -> ["village", "block", "district", "state"]. Spaces around keys and
    empty entries (stray commas) are ignored, and a key listed twice is kept once. Also used by
    CompanyStateMachine.clean() to store the normalised form, so admin typos never reach the lookup.
    """
    keys = []
    for key in (raw_profile_key or "").split(","):
        key = key.strip()
        if key and key not in keys:
            keys.append(key)
    return keys


def _lookup(user_profile, key):
    """Walk a dotted path through nested dicts and lists, e.g. 'organizations.0.name'."""
    value = user_profile
    for part in key.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return None
    return value


def _profile_value(user_profile, key):
    """The profile's value for `key` as a non-empty string, or None if it is missing or unusable."""
    value = _lookup(user_profile, key)
    if value is None or isinstance(value, (dict, list)):
        return None
    value = str(value).strip()
    return value or None


def get_profile_answer(state_machine, user_profile):
    """
    Return the profile value to auto-fill this step with, or None if the user must be asked.

    `state_machine` may be a model instance or a `.values()` dict. Returns None (ask the user) when:
      - the step is missing or not linked to the profile, or has no profile_key
      - there is no profile (guest) or the profile has no value for the key
      - with several keys: the profile is missing a value for ANY of them (no partial answers)
      - the value is empty / whitespace only
      - the step is a MULTIPLE_CHOICE question and the value matches none of its choices,
        since saving an answer the step would never accept is worse than asking.
    One key returns the bare value ("Bangalore"); several keys return their values comma-separated in
    the configured order ("Rampur, Hosakote, Bangalore, Karnataka").
    Numbers (e.g. a pincode stored as int) are converted to strings.
    """
    if not state_machine or not _get(state_machine, "is_linked_to_profile"):
        return None

    profile_keys = parse_profile_keys(_get(state_machine, "profile_key"))
    if not profile_keys or not isinstance(user_profile, dict):
        return None
    profile_key = ",".join(profile_keys)

    values = [_profile_value(user_profile, key) for key in profile_keys]
    if any(value is None for value in values):
        return None

    value = ", ".join(values)

    if _get(state_machine, "validation_type") == ValidationTypeChoices.MULTIPLE_CHOICE:
        choices = (_get(state_machine, "validation_config") or {}).get("choices") or []
        # Accept the value if it equals any choice's key or English label (case-insensitive).
        # A step with no choices configured has nothing to validate against, so it is allowed.
        # A combined multi-key answer will normally match no choice, so such a step is asked.
        accepted = {
            str(option).strip().lower()
            for choice in choices if isinstance(choice, dict)
            for option in (choice.get("key"), choice.get("label")) if option
        }
        if accepted and value.lower() not in accepted:
            logger.info(
                f"profile_autofill: value for key '{profile_key}' does not match the choices of "
                f"step {_get(state_machine, 'step')}; asking the user instead"
            )
            return None

    return value


def auto_fill_profile_steps(chat_session, company_bot, start_step, user_profile, profile_id, language):
    """
    Starting at `start_step`, auto-answer consecutive profile-linked steps.

    For every step answered this way two CompanyChat rows are saved, in the same order a normal
    exchange produces them: the bot question (AI -> user) and the profile value (user -> AI).
    Both carry `other_params = {"source": "profile", "profile_key": ..., "auto_filled": True}` so
    auto-filled answers can be told apart from typed ones later. They are not pushed to the
    frontend; the user only sees the next question that really needs an answer (A7).

    `company_bot` may be a CompanyBot instance or its id.

    Returns:
        {
            "step": first step that must be asked, or the bot's last step when `completed`,
            "filled_steps": [step numbers that were auto-filled],
            "completed": True when the auto-fill answered every remaining step of the flow,
        }
    The step numbers move forward only; `chat_session` is NOT modified or saved here, so the
    caller stays in charge of `current_step` / `session_status`, as it is today.
    """
    result = {"step": start_step, "filled_steps": [], "completed": False}

    # Nothing to fill from (guest / empty profile): skip the DB work entirely.
    if not user_profile or not isinstance(user_profile, dict):
        return result

    try:
        company_bot_id = getattr(company_bot, "id", company_bot)

        # One query for every remaining step; the loop below walks them in step order. Step numbers
        # may have gaps (e.g. 1, 2, 5), so the step after 2 is 5, not 3.
        steps = {
            state["step"]: state
            for state in CompanyStateMachine.objects.filter(
                company_bot_id=company_bot_id, step__gte=start_step
            ).values(*_STEP_FIELDS)
        }

        # The caller lands on start_step; if that step doesn't exist there is nothing to fill.
        if start_step not in steps:
            return result

        to_fill = []
        next_unfilled_step = None
        for step in sorted(steps):
            value = get_profile_answer(steps[step], user_profile)
            if value is None:
                next_unfilled_step = step
                break
            to_fill.append((steps[step], value))

        if not to_fill:
            return result

        ai_profile = get_ai_profile()

        for state, value in to_fill:
            meta = {"source": "profile", "profile_key": ",".join(parse_profile_keys(state["profile_key"])),
                    "auto_filled": True}

            # Question row: English text in `message`, cached translation (if any) in
            # `translated_message`, the same layout a normally asked question has. No live
            # translation call, since the user never sees this question.
            cached = (state["translations"] or {}).get(language, {}) if language and language != "en" else {}
            # Created directly instead of via save_in_company_db, which overwrites the previous
            # row when two consecutive messages share a sender.
            CompanyChat.objects.create(
                message=state["bot_question"] or "",
                translated_message=cached.get("text") if isinstance(cached, dict) else None,
                session=chat_session.session,
                status=ChatStatus.COMPLETED,
                sender=ai_profile,
                receiver_id=profile_id,
                stage=state["name"],
                other_params=meta,
            )
            # Answer row: the profile value exactly as stored, regardless of the chat language (A5).
            CompanyChat.objects.create(
                message=value,
                translated_message=None,
                session=chat_session.session,
                status=ChatStatus.COMPLETED,
                sender_id=profile_id,
                receiver=ai_profile,
                stage=state["name"],
                other_params=meta,
            )
            result["filled_steps"].append(state["step"])

        if next_unfilled_step is not None:
            result["step"] = next_unfilled_step
        else:
            # Ran past the final step: the whole rest of the flow came from the profile. Report the
            # last real step (max step number), not step + 1, so the frontend's step counter
            # never points past the flow.
            result["step"] = max(steps)
            result["completed"] = True

        logger.info(
            f"profile_autofill: session={chat_session.session} auto-filled steps={result['filled_steps']} "
            f"next_step={result['step']} completed={result['completed']}"
        )
        return result

    except Exception as e:
        # Never break the chat over auto-fill. Rows already written stay (they are correct
        # answers); report what was filled so far so the caller resumes from the right step.
        logger.exception(f"profile_autofill: failed for session={getattr(chat_session, 'session', None)}: {e}")
        if result["filled_steps"]:
            result["step"] = result["filled_steps"][-1] + 1
        return result