# Utilities for recording per-call provider costs and reading pricing config.
# Called from Celery tasks and sync provider code — not safe to call from
# the async WebSocket consumer directly.
#
# Public API:
#   record_usage_cost()            — writes one UsageCostLog row and updates ChatSession.total_cost
#   get_pricing_from_voice_provider() — reads cost_per_1k_units from Voice.other_params.pricing
import logging
from decimal import Decimal

from django.db.models import F

from chatbot.models import ChatSession, CompanyBot, Profile, UsageCostLog

logger = logging.getLogger('django')


# Purpose:      Persists one billable provider call as a UsageCostLog row and
#               atomically increments ChatSession.total_cost.
# Inputs:       session      — ChatSession instance or session ID string.
#               call_type    — UsageCallType value (LLM, TTS, STT, TRANSLATE, TRANSLITERATE).
#               provider     — External service name (optional).
#               model_name   — Specific model/voice used (optional).
#               input_units  — Tokens, characters, or seconds depending on call_type.
#               output_units — Same unit type as input_units for the response side.
#               input_cost   — USD cost for input (float or Decimal).
#               output_cost  — USD cost for output (float or Decimal).
#               total_cost   — Combined cost; if non-zero, increments ChatSession.total_cost.
#               other_params — Dict of provider-specific metadata to store.
# Output:       Created UsageCostLog instance, or None on failure (never raises).
# Side effects: Inserts a UsageCostLog row; atomically increments ChatSession.total_cost
#               at DB level via F() to avoid race conditions across Celery workers.
def record_usage_cost(
        session, call_type, provider=None, model_name=None, profile=None, company_bot=None,
        input_units=0, output_units=0, input_cost=0, output_cost=0, total_cost=0, other_params=None
):
    try:
        if isinstance(session, ChatSession):
            chat_session = session
        else:
            chat_session = ChatSession.objects.filter(session=session).first()

        if not chat_session:
            logger.warning(f"record_usage_cost: no ChatSession found for session={session}")
            return None

        if profile is None:
            profile = chat_session.profile
        elif not isinstance(profile, Profile):
            profile = Profile.objects.filter(pk=profile).first()

        if not isinstance(company_bot, CompanyBot):
            company_bot = chat_session.company_bot

        # Convert via str to avoid float-to-Decimal precision loss.
        total_cost = Decimal(str(total_cost or 0))

        usage_log = UsageCostLog.objects.create(
            session=chat_session,
            profile=profile,
            company_bot=company_bot,
            call_type=call_type,
            provider=provider,
            model_name=model_name,
            input_units=input_units or 0,
            output_units=output_units or 0,
            input_cost=Decimal(str(input_cost or 0)),
            output_cost=Decimal(str(output_cost or 0)),
            total_cost=total_cost,
            other_params=other_params,
        )

        # F() expression performs the increment at DB level, avoiding race
        # conditions when multiple Celery workers record cost for the same session.
        if total_cost:
            ChatSession.objects.filter(pk=chat_session.pk).update(total_cost=F('total_cost') + total_cost)

        return usage_log
    except Exception as e:
        logger.error(f"record_usage_cost failed for session={session}: {e}", exc_info=True)
        return None


# Purpose: Reads cost_per_1k_units from Voice.other_params.pricing, mirroring
#          the CompanyBot.other_params.model_pricing convention for LLM pricing.
# Inputs:  voice_provider — Voice model instance.
# Output:  Float cost per 1,000 units, or None if not configured.
#          Returns None silently on missing or malformed config (never raises).
def get_pricing_from_voice_provider(voice_provider):
    try:
        other_params = getattr(voice_provider, 'other_params', None) or {}
        pricing = other_params.get('pricing') or {}
        cost_per_1k = pricing.get('cost_per_1k_units')
        return float(cost_per_1k) if cost_per_1k is not None else None
    except (AttributeError, TypeError, ValueError):
        return None
