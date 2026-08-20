from chatbot.cron_tasks.guest_discussion.state_categorisation import (
    _matches,
    _normalize_text,
    load_mapping_from_bot,
)
from chatbot.models import CompanyBot, Story
from django.db.models import Q
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger('django')


# -------------- CORE CATEGORISATION ------------------

def _match_district(district_text: str, mapping_data: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """
    Match other_params.district text against mapping district names/patterns
    across all states; first match wins and its state is inferred.
    """
    result: Dict[str, Optional[str]] = {'state': None, 'district': None, 'organisation': None}

    if not district_text or not mapping_data:
        return result

    district_text = _normalize_text(district_text)
    states: List[Dict] = mapping_data.get('states', [])

    for state in states:
        for district in state['districts']:
            if _matches(district['name'], district_text) or any(
                _matches(p, district_text) for p in district['matching_patterns']
            ):
                result['state'] = state['name']
                result['district'] = district['name']
                result['organisation'] = district.get('organisation')
                return result

    return result


def categorise_story(story: Story, mapping_data: Dict[str, Any]) -> Optional[Dict[str, Optional[str]]]:
    """
    Categorise a listening-activity story using other_params.district only.
    Returns None when no usable district text exists.
    """
    district_text: Optional[str] = None
    if story.other_params:
        val = story.other_params.get('district')
        if val and isinstance(val, str):
            district_text = val

    if not district_text:
        return None

    return _match_district(district_text, mapping_data)


# -------------- MAIN ------------------

def run_district_categorisation(story_queryset=None, mapping_data: Dict[str, Any] | None = None, company_bot=None) -> Dict[str, Any]:
    """
    Main entry point. Processes listening-activity stories missing state or district.
    mapping_data source: explicit mapping_data > company_bot.dynamic_context.
    """
    if mapping_data is None:
        if company_bot is None:
            logger.error("company_bot required for mapping data; aborting district categorisation")
            return {'processed': 0, 'skipped': 0, 'failed': []}
        mapping_data = load_mapping_from_bot(company_bot)

    if not mapping_data:
        logger.error("No mapping data available; aborting district categorisation")
        return {'processed': 0, 'skipped': 0, 'failed': []}

    if story_queryset is None:
        story_queryset = Story.objects.filter(
            other_params__flow='listening-activity',
        ).filter(
            Q(state__isnull=True) | Q(district__isnull=True)
        )

    stories = list(story_queryset)
    logger.info(f"Starting district categorisation for {len(stories)} stories")

    processed = 0
    skipped = 0
    failed: List[int] = []

    for story in stories:
        try:
            categorisation = categorise_story(story, mapping_data)
            if categorisation is None:
                skipped += 1
                continue

            if categorisation['state'] or categorisation['district']:
                story.state = categorisation['state']
                story.district = categorisation['district']
                story.save(update_fields=['state', 'district'])
                logger.info(f"Updated story {story.id}: state={categorisation['state']}, district={categorisation['district']}")
                processed += 1
            else:
                skipped += 1

        except Exception as e:
            logger.error(f"Error categorising story {story.id}: {e}")
            failed.append(story.id)

    summary = {
        'total': len(stories),
        'processed': processed,
        'skipped': skipped,
        'failed': failed,
    }

    logger.info(
        f"District categorisation complete — "
        f"processed: {summary['processed']}, skipped: {summary['skipped']}, failed: {len(failed)}"
    )
    return summary


# -------------- CRON ENTRY POINT ------------------

def run_cron() -> None:
    try:
        bot = CompanyBot.objects.get(route='/state-classification-guest-discussion')
    except CompanyBot.DoesNotExist:
        logger.error("CompanyBot with route '/state-classification-guest-discussion' not found")
        return
    except CompanyBot.MultipleObjectsReturned:
        logger.error("Multiple CompanyBots with route '/state-classification-guest-discussion' found")
        return
    run_district_categorisation(company_bot=bot)


# -------------- CONVENIENCE ENTRY POINTS ------------------

def run_for_story_ids(story_ids: List[int], mapping_data: Dict[str, Any] | None = None, company_bot=None) -> Dict[str, Any]:
    stories = Story.objects.filter(id__in=story_ids)
    return run_district_categorisation(story_queryset=stories, mapping_data=mapping_data, company_bot=company_bot)


def run_for_date_range(start_date, end_date, mapping_data: Dict[str, Any] | None = None, company_bot=None) -> Dict[str, Any]:
    stories = Story.objects.filter(
        other_params__flow='listening-activity',
        created_at__gte=start_date,
        created_at__lte=end_date,
        state__isnull=True,
    )
    return run_district_categorisation(story_queryset=stories, mapping_data=mapping_data, company_bot=company_bot)
