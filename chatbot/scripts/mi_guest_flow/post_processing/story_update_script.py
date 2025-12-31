import asyncio
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.utils.timezone import make_aware
from jinja2 import Template

from chatbot.models import (
    Story,
    ChatSession,
    SessionFlowName,
    CompanyBot,
    Voice,
    VoiceType,
    CompanyChat,
    BotVernacular,
)
from chatbot.utils.chat_utils import get_guided_chat
from chatbot.utils.story_utils.common.generic_story_tasks import (
    save_generic_story,
    translate_to_english_if_needed
)
from chatbot.utils.story_utils.get_story_prompts import (
    get_tool_values,
    get_creation_promt, get_validation_prompt
)
from chatbot.utils.story_utils.story_llm import generate_story_llm

logger = logging.getLogger("django")


def resolve_date_range(start_date=None, end_date=None):
    if start_date and end_date:
        return make_aware(start_date), make_aware(end_date)

    yesterday = datetime.now() - timedelta(days=1)
    start = make_aware(datetime(yesterday.year, yesterday.month, yesterday.day, 0, 0, 0))
    end = make_aware(datetime(yesterday.year, yesterday.month, yesterday.day, 23, 59, 59))
    return start, end


def get_sessions_from_story_flow(start_date=None, end_date=None):
    start_time, end_time = resolve_date_range(start_date, end_date)

    session_ids = (
        Story.objects
        .filter(
            created_at__range=(start_time, end_time),
            other_params__flow=SessionFlowName.GuestMiStory
        )
        .values_list("session", flat=True)
    )

    sessions = (
        ChatSession.objects
        .filter(session__in=session_ids)
        .select_related("profile")
    )

    logger.info(f"Fetched {len(sessions)} sessions")
    print(f"[INFO] Fetched {len(sessions)} sessions")

    return list(sessions)


def process_session(session, access_token):
    try:
        session_id = session.session
        profile = session.profile
        language = session.language or "en"

        logger.info(f"Processing session {session_id}")
        print(f"[INFO] Processing session {session_id}")

        company_bot = CompanyBot.objects.get(route="/story_temp")
        validate_bot = CompanyBot.objects.get(route="/story_temp_validate")

        voice_provider = Voice.objects.filter(
            company_bot=company_bot,
            type=VoiceType.TextToText,
            language=language
        ).first()

        company_chats = CompanyChat.objects.filter(
            session=session_id
        ).order_by("created_at")

        intro_to_pass = None
        flow_bot = CompanyBot.objects.get(company=profile.company, route="/guided_guest")
        bot_vernacular = BotVernacular.objects.filter(company_bot=flow_bot).first()

        if bot_vernacular:
            intro_to_pass = (
                bot_vernacular.introductory_message
                if access_token else
                bot_vernacular.alt_introductory_message
            )

        messages = get_guided_chat(
            company_bot=company_bot,
            company_chats=company_chats,
            intro=intro_to_pass
        )

        formatted_content_prompt, formatted_story_prompt, _, _ = get_creation_promt(
            company_bot=company_bot,
            profile=profile
        )

        tool_content, tool_story = get_tool_values(company_bot=company_bot)

        logger.info(f"Calling primary LLM for session {session_id}")
        print(f"[INFO] Calling primary LLM for session {session_id}")

        response_json_content, _ = asyncio.run(
            generate_story_llm(
                formatted_content_prompt=formatted_content_prompt,
                formatted_story_prompt=formatted_story_prompt,
                messages=messages,
                tool_content=tool_content,
                tool_story=tool_story,
                company_bot=company_bot,
                flow=SessionFlowName.GuestMiStory
            )
        )

        if not isinstance(response_json_content, dict):
            logger.error(f"Initial LLM response is not JSON for session {session_id}")
            print(f"[ERROR] Initial LLM response is not JSON for session {session_id}")
            raise Exception("Initial LLM response is not JSON")

        validate_content_prompt, validate_story_prompt = get_validation_prompt(
            response_json_story=response_json_content,
            validate_bot=validate_bot,
            response_json_content=response_json_content,
            tag_context="",
            project_data="",
            profile=profile
        )

        print("=" * 70)
        print("validate_content_prompt:")
        print(validate_content_prompt)
        print("=" * 70)

        tool_content, tool_story = get_tool_values(company_bot=validate_bot)

        logger.info(f"Calling validation LLM for session {session_id}")
        print(f"[INFO] Calling validation LLM for session {session_id}")

        validated_response, _ = asyncio.run(
            generate_story_llm(
                formatted_content_prompt=validate_content_prompt,
                formatted_story_prompt=validate_story_prompt,
                messages=messages,
                tool_content=tool_content,
                tool_story=tool_story,
                company_bot=validate_bot,
                flow=SessionFlowName.GuestMiStory
            )
        )

        if isinstance(validated_response, dict):
            response_json_content = validated_response
        else:
            logger.error(f"Validation LLM returned invalid JSON for session {session_id}")
            print(f"[ERROR] Validation LLM returned invalid JSON for session {session_id}")
            raise Exception("Validation LLM failed")

        if "challenge" in response_json_content:
            response_json_content.setdefault(
                "problem_statement",
                response_json_content.get("challenge")
            )

            response_json_content.pop("challenge", None)

        logger.info(f"Saving story for session {session_id}")
        print(f"[INFO] Saving story for session {session_id}")

        save_generic_story(
            response_json_story=response_json_content,
            language=language,
            voice_provider=voice_provider,
            profile=profile,
            session=session_id,
            combined_reason="",
            flow=SessionFlowName.GuestMiStory,
            company_bot=company_bot,
            exclude_fields=['problem_statement']
        )

        if response_json_content.get("problem_statement"):
            from shikshalokam.models import Project, ProjectVernacular
            from chatbot.utils.story_utils.format_utils import clean_escaped_text
            from chatbot.utils.story_llama_utils import translate_field
            import json

            raw_problem = response_json_content.get("problem_statement", "")
            raw_title = response_json_content.get("title", "")

            english_problem = clean_escaped_text(
                translate_to_english_if_needed(raw_problem, voice_provider, language)
            )
            english_title = clean_escaped_text(
                translate_to_english_if_needed(raw_title, voice_provider, language)
            )

            story = Story.objects.filter(session=session_id).first()
            if not story:
                return session_id, True

            project = Project.objects.filter(story=story).first()
            if not project:
                return session_id, True

            project.actual_problem_statement = english_problem
            project.actual_title = english_title
            project.save(update_fields=["actual_problem_statement", "actual_title"])

            if language != "en":
                translated_problem = translate_field(
                    voice_provider, english_problem, language, "en"
                )
                translated_title = translate_field(
                    voice_provider, english_title, language, "en"
                )

                project_vernacular, _ = ProjectVernacular.objects.get_or_create(
                    project=project,
                    language=language,
                    defaults={"details": "{}"}
                )

                details = json.loads(project_vernacular.details or "{}")
                details.setdefault("project", {})
                details["project"].update({
                    "actual_problem_statement": translated_problem,
                    "actual_title": translated_title
                })

                project_vernacular.details = json.dumps(details)
                project_vernacular.save(update_fields=["details"])

        logger.info(f"Session {session_id} processed successfully")
        print(f"[INFO] Session {session_id} processed successfully")

        return session_id, True

    except Exception as e:
        logger.error(f"Failed for session {session.session}: {str(e)}", exc_info=True)
        print(f"[ERROR] Failed for session {session.session}: {str(e)}")
        return session.session, False


def create_stories_parallel(sessions, access_token, max_workers=4):
    succeeded = []
    failed = []

    logger.info(f"Running with ThreadPoolExecutor (workers={max_workers})")
    print(f"[INFO] Running with ThreadPoolExecutor (workers={max_workers})")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(process_session, session, access_token)
            for session in sessions
        ]

        for future in as_completed(futures):
            session_id, success = future.result()
            if success:
                succeeded.append(session_id)
            else:
                failed.append(session_id)

    logger.info(f"Success count: {len(succeeded)}")
    logger.info(f"Failure count: {len(failed)}")
    print(f"[INFO] Success count: {len(succeeded)}")
    print(f"[INFO] Failure count: {len(failed)}")

    return succeeded, failed


def run_story_update_from_temp_bot(
    access_token,
    start_date=None,
    end_date=None,
    max_workers=4,
    session_ids=None
):
    logger.info("Starting story update pipeline")
    print("[INFO] Starting story update pipeline")

    if session_ids:
        sessions = (
            ChatSession.objects
            .filter(session__in=session_ids)
            .select_related("profile")
        )
    else:
        sessions = get_sessions_from_story_flow(start_date, end_date)

    if not sessions:
        logger.info("No sessions found to process")
        print("[INFO] No sessions found to process")
        return [], []

    succeeded, failed = create_stories_parallel(
        sessions=sessions,
        access_token=access_token,
        max_workers=max_workers
    )

    logger.info(f"Pipeline completed. Success: {len(succeeded)}, Failed: {len(failed)}")
    print(f"[INFO] Pipeline completed. Success: {len(succeeded)}, Failed: {len(failed)}")

    return succeeded, failed
