import traceback
from chatbot.models import (Profile, CompanyChat, CompanyBot,
                            ChatSession, ChatStatus, Voice, VoiceType, SessionFlowName)
from chatbot.utils.chat_utils import get_guided_chat
from chatbot.utils.shikshalokam_mitra_utils import get_stored_conversation, get_stored_chathistory
from chatbot.utils.shikshalokam_story_utils import save_shikshalokam_story
from chatbot.utils.story_llama_utils import translate_field
import asyncio

from chatbot.utils.story_utils.format_utils import get_formatted_story
from chatbot.utils.story_utils.get_story_prompts import get_creation_promt, get_chat_message, get_tool_values, \
    get_validation_prompt
from chatbot.utils.story_utils.story_llm import generate_story_llm, validate_story_llm
from chatbot.utils.story_utils.story_tasks import save_story, save_chaupal_report


def create_story_object(profile_id, session, access_token, flow, language='en'):
    voice_provider=None
    try:
        profile = Profile.objects.filter(id=profile_id).first()
        company_chats = CompanyChat.objects.filter(session=session).order_by('created_at')
        if profile:
            if flow in [SessionFlowName.LoginMiStory, SessionFlowName.GuestMiStory, SessionFlowName.Reflection]:
                company_bot = CompanyBot.objects.get(company=profile.company, route='/story')
                validate_bot = CompanyBot.objects.get(company=profile.company, route='/story_validation')
            else:
                company_bot = CompanyBot.objects.get(company=profile.company, route='/chaupal-story')
                validate_bot = CompanyBot.objects.get(company=profile.company, route='/chaupal-_validation')
        else:
            if flow in [SessionFlowName.LoginMiStory, SessionFlowName.GuestMiStory, SessionFlowName.Reflection]:
                company_bot = CompanyBot.objects.get(route='/story')
                validate_bot = CompanyBot.objects.get(route='/story_validation')
            else:
                company_bot = CompanyBot.objects.get(route='/chaupal-story')
                validate_bot = CompanyBot.objects.get(route='/chaupal-_validation')

        voice_provider = Voice.objects.filter(company_bot=company_bot, type=VoiceType.TextToText).first()

        chat_session = ChatSession.objects.get(session=session)

        formatted_content_prompt, formatted_story_prompt, tag_context, project_data = get_creation_promt(
            company_bot=company_bot, profile=profile
        )

        messages = get_guided_chat(
            company_bot=company_bot, company_chats=company_chats
        )

        tool_content, tool_story = get_tool_values(company_bot=company_bot)

        response_json_content, response_json_story = asyncio.run(
            generate_story_llm(
                formatted_content_prompt=formatted_content_prompt, formatted_story_prompt=formatted_story_prompt,
                messages=messages, tool_content=tool_content, tool_story=tool_story, company_bot=company_bot,
                flow=flow
            )
        )
        print("Using profile: ", profile)

        validate_content_prompt, validate_story_prompt = get_validation_prompt(
            response_json_story=response_json_story, validate_bot=validate_bot,
            response_json_content=response_json_content, tag_context=tag_context, project_data=project_data,
            profile=profile
        )

        tool_content, tool_story = get_tool_values(company_bot=validate_bot)

        if company_bot.provider != validate_bot.provider:
            print("Provider is not same! Getting new message format.")
            messages = get_guided_chat(
                company_bot=validate_bot, company_chats=company_chats
            )

        response_json_story, combined_reason = asyncio.run(
            validate_story_llm(
                formatted_content_prompt=validate_content_prompt, formatted_story_prompt=validate_story_prompt,
                messages=messages, tool_content=tool_content, tool_story=tool_story, company_bot=validate_bot,
                flow=flow
            )
        )
        if flow in [SessionFlowName.LoginMiStory, SessionFlowName.GuestMiStory, SessionFlowName.Reflection]:
            story, problem_statement = save_story(
                response_json_story=response_json_story, language=language, voice_provider=voice_provider,
                profile=profile, session=session, combined_reason=combined_reason, flow=flow,
                project_id=chat_session.project_id
            )
        else:
            story, problem_statement = save_chaupal_report(
                response_json_story=response_json_story, language=language, voice_provider=voice_provider,
                profile=profile, session=session, combined_reason=combined_reason, flow=flow,
                messages=messages
            )
        if story:
            formatted_content = get_formatted_story(story)
            if formatted_content:
                story.formatted_content = formatted_content
                story.save(update_fields=['formatted_content'])

        chat_session.session_status = ChatStatus.COMPLETED
        chat_session.save(update_fields=['session_status'])
        chat_session.save_title(language=language)

        if flow == SessionFlowName.Reflection:
            conversation = get_stored_conversation(company_chats=company_chats)
            chat_history = get_stored_chathistory(company_chats=company_chats)
        else:
            conversation, chat_history = [], []

        save_shikshalokam_story(
            story=story, profile=profile,
            problem_statement=problem_statement, chat_history=chat_history, access_token=access_token,
            project_id=None, session=session, conversation=conversation, flow=flow
        )

        story_id = story.id if story and story.id else ""
        story_content = story.content if story and story.content else ""

        return story_id, story_content, ""

    except Exception as e:
        traceback.print_exc()
        error_message = "Our server's taking a breather! Give it a moment and try again."
        if voice_provider and language != 'en':
            error_message = translate_field(
                voice_provider=voice_provider, message_body=error_message, target_language=language
            )
        return "", "", error_message
