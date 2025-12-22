import asyncio
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.utils.timezone import make_aware

from chatbot.models import (
    Story,
    ChatSession,
    SessionFlowName,
    CompanyBot,
    Voice,
    VoiceType, CompanyChat, BotVernacular,
)
from chatbot.utils.chat_utils import get_guided_chat
from chatbot.utils.story_utils.common.generic_story_tasks import save_generic_story, translate_to_english_if_needed
from chatbot.utils.story_utils.get_story_prompts import get_tool_values, get_creation_promt
from chatbot.utils.story_utils.story_llm import generate_story_llm

logger = logging.getLogger("django")


# ------------------------------------------------
# DATE RANGE RESOLVER
# ------------------------------------------------
def resolve_date_range(start_date=None, end_date=None):
    """
    If start_date and end_date are None,
    default to previous day (00:00:00 → 23:59:59)
    """
    if start_date and end_date:
        start = make_aware(start_date)
        end = make_aware(end_date)
        return start, end

    yesterday = datetime.now() - timedelta(days=1)

    start = make_aware(datetime(yesterday.year, yesterday.month, yesterday.day, 0, 0, 0))
    end = make_aware(datetime(yesterday.year, yesterday.month, yesterday.day, 23, 59, 59))

    logger.info(f"Using previous day date range: {start} → {end}")
    print(f"[INFO] Using previous day date range: {start} → {end}")

    return start, end


# ------------------------------------------------
# STEP 1: GET SESSIONS FROM EXISTING STORIES
# ------------------------------------------------
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

    logger.info(f"Fetched {len(sessions)} sessions from {start_time} → {end_time}")
    print(f"[INFO] Fetched {len(sessions)} sessions from {start_time} → {end_time}")

    return list(sessions)


# ------------------------------------------------
# STEP 2: WORKER FUNCTION (SINGLE SESSION)
# ------------------------------------------------
def process_session(session, access_token):
    try:
        session_id = session.session
        profile = session.profile
        language = session.language or "en"

        logger.info(f"Processing session {session_id}")
        print(f"[INFO] Processing session {session_id}")

        company_bot = CompanyBot.objects.get(route="/story_temp")

        voice_provider = Voice.objects.filter(
            company_bot=company_bot,
            type=VoiceType.TextToText,
            language=language
        ).first()
        company_chats = CompanyChat.objects.filter(session=session_id).order_by('created_at')

        intro_to_pass = None
        route_to_use = '/guided_guest'
        flow_company_bot = CompanyBot.objects.get(company=profile.company, route=route_to_use)
        bot_vernacular = BotVernacular.objects.filter(company_bot=flow_company_bot).first()
        if bot_vernacular:
            if access_token:
                intro_to_pass = bot_vernacular.introductory_message
                if profile and profile.first_name and intro_to_pass:
                    words = intro_to_pass.split(" ", 1)
                    if len(words) > 1:
                        intro_to_pass = f"{words[0]} {profile.first_name} {words[1]}"
                    else:
                        intro_to_pass = f"{words[0]} {profile.first_name}"
            else:
                intro_to_pass = bot_vernacular.alt_introductory_message

        messages = get_guided_chat(
            company_bot=company_bot,
            company_chats=company_chats,
            intro=intro_to_pass
        )


        formatted_content_prompt, formatted_story_prompt, tag_context, project_data = get_creation_promt(
            company_bot=company_bot, profile=profile
        )

        print("formatted_content_prompt: ", formatted_content_prompt)
        print("\n\n\n\nformatted_story_prompt: ", formatted_story_prompt)

        tool_content, tool_story = get_tool_values(company_bot=company_bot)

        response_json_content,_ = asyncio.run(
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

        print('response_json_content: ', response_json_content)

        if not isinstance(response_json_content, dict):
            raise Exception("LLM response is not JSON")

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

        if response_json_content.get('problem_statement'):
            from shikshalokam.models import Project, ProjectVernacular
            from chatbot.utils.story_utils.format_utils import clean_escaped_text
            from chatbot.utils.story_llama_utils import translate_field
            import json

            raw_problem_statement = response_json_content.get('problem_statement', '')
            raw_title = response_json_content.get('title', '')

            english_problem_statement = clean_escaped_text(
                text=translate_to_english_if_needed(raw_problem_statement, voice_provider, language)
            )

            english_title = clean_escaped_text(
                text=translate_to_english_if_needed(raw_title, voice_provider, language)
            )

            story = Story.objects.filter(session=session_id).first()

            if story:
                project = Project.objects.filter(story=story).first()

                if project:
                    project.actual_problem_statement = english_problem_statement
                    project.actual_title = english_title
                    project.save(update_fields=['actual_problem_statement', 'actual_title'])
                    logger.info(f"Updated project {project.project_id} with problem_statement")

                    if language != 'en':
                        translated_problem_statement = translate_field(
                            voice_provider=voice_provider,
                            message_body=english_problem_statement,
                            target_language=language,
                            source_language='en'
                        )

                        translated_title = translate_field(
                            voice_provider=voice_provider,
                            message_body=english_title,
                            target_language=language,
                            source_language='en'
                        )

                        project_vernacular = ProjectVernacular.objects.filter(
                            project=project,
                            language=language
                        ).first()

                        if project_vernacular:
                            try:
                                details = json.loads(project_vernacular.details)
                                if 'project' not in details:
                                    details['project'] = {}
                                details['project']['actual_problem_statement'] = translated_problem_statement
                                details['project']['actual_title'] = translated_title
                                project_vernacular.details = json.dumps(details)
                                project_vernacular.save(update_fields=['details'])
                                logger.info(f"Updated ProjectVernacular for project {project.project_id} in {language}")
                            except json.JSONDecodeError:
                                logger.error(
                                    f"Could not parse ProjectVernacular details for project {project.project_id}")
                        else:
                            ProjectVernacular.objects.create(
                                project=project,
                                language=language,
                                details=json.dumps({
                                    "project": {
                                        "actual_problem_statement": translated_problem_statement,
                                        "actual_title": translated_title
                                    }
                                })
                            )
                            logger.info(f"Created ProjectVernacular for project {project.project_id} in {language}")
                else:
                    logger.info(f"No project found for story in session {session_id}")

        logger.info(f"Story updated for session {session_id}")
        print(f"[INFO] Story updated for session {session_id}")

        return session_id, True

    except Exception as e:
        logger.error(f"Failed for session {session.session}: {str(e)}", exc_info=True)
        print(f"[ERROR] Failed for session {session.session}: {str(e)}")
        return session.session, False


# ------------------------------------------------
# STEP 3: PARALLEL RUNNER
# ------------------------------------------------
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
    print(f"[INFO] Success count: {len(succeeded)}")

    logger.info(f"Failure count: {len(failed)}")
    print(f"[INFO] Failure count: {len(failed)}")

    return succeeded, failed


# ------------------------------------------------
# STEP 4: ORCHESTRATOR (ONE ENTRY POINT)
# ------------------------------------------------
def run_story_update_from_temp_bot(
    access_token,
    start_date=None,
    end_date=None,
    max_workers=4,
    session_ids=None
):
    logger.info("Starting story update pipeline (story_temp bot)")
    print("[INFO] Starting story update pipeline (story_temp bot)")

    # ------------------------------------------------
    # MANUAL SESSION OVERRIDE
    # ------------------------------------------------
    if session_ids:
        logger.info(f"Manual session override provided: {session_ids}")
        print(f"[INFO] Manual session override provided: {session_ids}")

        sessions = (
            ChatSession.objects
            .filter(session__in=session_ids)
            .select_related("profile")
        )

    else:
        sessions = get_sessions_from_story_flow(start_date, end_date)

    total = len(sessions)

    if not sessions:
        logger.info("No sessions found to process")
        print("[INFO] No sessions found to process")
        return [], []

    logger.info(f"Found {total} sessions to process")
    print(f"[INFO] Found {total} sessions to process")

    succeeded, failed = create_stories_parallel(
        sessions=sessions,
        access_token=access_token,
        max_workers=max_workers
    )

    logger.info("Story update pipeline completed")
    print("[INFO] Story update pipeline completed")

    logger.info(f"Total succeeded: {len(succeeded)} / {total}")
    print(f"[INFO] Total succeeded: {len(succeeded)} / {total}")

    logger.info(f"Total failed: {len(failed)} / {total}")
    print(f"[INFO] Total failed: {len(failed)} / {total}")

    return succeeded, failed
