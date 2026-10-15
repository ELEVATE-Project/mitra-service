import logging

from django.db.models import Exists, OuterRef
from rapidfuzz import fuzz, process

from chatbot.models import ChatSession, CompanyChat
from chatbot.models.story_models import Story

logger = logging.getLogger('django')

SESSION_TYPE = 'stakeholder-fgd'
STAGE = 'STATE_6'
FUZZY_THRESHOLD = 80

DISTRICTS = [
    'Kaimur',
    'Muzaffarpur',
    'West Champaran',
    'Rohtas',
    'Sheohar',
]

# Alias map for known alternate spellings not caught by fuzzy threshold
ALIAS_MAP = {
    'shivhar': 'Sheohar',
    'sivhar': 'Sheohar',
    'chamaparan': 'West Champaran',
    'paschim champaran': 'West Champaran',
    'pashchim champaran': 'West Champaran',
    'pashchimi champaran': 'West Champaran',
    'champaran': 'West Champaran',
}

_DISTRICTS_LOWER = [d.lower() for d in DISTRICTS]


def _classify(message: str) -> str | None:
    normalized = message.strip().lower()
    if not normalized:
        return None

    for alias, district in ALIAS_MAP.items():
        if alias in normalized:
            return district

    result = process.extractOne(
        normalized,
        _DISTRICTS_LOWER,
        scorer=fuzz.token_sort_ratio,
        score_cutoff=FUZZY_THRESHOLD,
    )
    if result:
        _, _, idx = result
        return DISTRICTS[idx]

    return None


def classify_districts():
    story_exists = Story.objects.filter(session=OuterRef('session'))
    story_has_district = (
        Story.objects.filter(session=OuterRef('session'))
        .exclude(district__isnull=True)
        .exclude(district='')
    )

    chats = (
        CompanyChat.objects
        .filter(
            stage=STAGE,
            receiver_id=1,
            session__in=ChatSession.objects.filter(
                session_type=SESSION_TYPE,
            ).values('session'),
        )
        .filter(Exists(story_exists))
        .exclude(Exists(story_has_district))
        .values('session', 'translated_message', 'message')
    )

    total = chats.count()
    logger.info(f"district_classification: {total} sessions to classify")

    classified = 0
    skipped = 0

    for chat in chats:
        raw = chat['translated_message'] or chat['message'] or ''
        district = _classify(raw)

        if district is None:
            logger.info(
                f"district_classification: no match for '{raw}' "
                f"(session={chat['session']})"
            )
            skipped += 1
            continue

        Story.objects.filter(session=chat['session']).update(district=district)
        classified += 1

    logger.info(
        f"district_classification: done — classified={classified}, skipped={skipped}"
    )
