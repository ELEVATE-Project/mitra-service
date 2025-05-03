import traceback
from celery import shared_task

from chatbot.celery_tasks.common_chat_tasks import save_in_company_db
from chatbot.celery_tasks.handle_message import translate_and_send_message
from chatbot.models import CompanyChat, Profile, CompanyBot, ChatSession, BotVernacular, ChatStatus
from chatbot.models.company_models import CompanyStateMachine
from chatbot.utils.chat_utils import get_guided_chat
import logging
from chatbot.utils.chaupal_tool_call import get_chaupal_tool_call_response
from chatbot.utils.shiksha_chaupal.base_utils import get_guided_prompt
from chatbot.utils.shiksha_chaupal.date_utils import handle_date_prompt

logger = logging.getLogger('django')


@shared_task
def get_chaupal_response(channel_name, session_id, profile_id, route):
    try:
        company_chats = CompanyChat.objects.filter(session=session_id).order_by('created_at')
        print(session_id)
        chat_session = ChatSession.objects.filter(session=session_id).first()
        profile = Profile.objects.filter(id=profile_id).first()
        if profile:
            company_bot = CompanyBot.objects.get(company=profile.company, route='/shikshalokam_chaupal')
        else:
            company_bot = CompanyBot.objects.get(route='/shikshalokam_chaupal')
        state_machine = CompanyStateMachine.objects.get(company_bot=company_bot, step=chat_session.current_step)
        system_context = company_bot.context

        other_info = None
        bot_vernacular = BotVernacular.objects.filter(company_bot=company_bot).first()
        if bot_vernacular:
            if profile and profile.first_name:
                intro_mssg = bot_vernacular.introductory_message
                first_word = intro_mssg.split(" ")[0]
                remaining_message = " ".join(intro_mssg.split(" ")[1:])
                intro_mssg = f"{first_word} {profile.first_name}, {remaining_message}"
                profile_addresses = None
                if profile and profile.first_name:
                    profile_addresses = profile.profile_address.all().first()
                address_components = [
                    profile_addresses.district if profile_addresses and profile_addresses.district else "",
                    profile_addresses.block if profile_addresses and profile_addresses.block else "",
                    profile_addresses.state if profile_addresses and profile_addresses.state else ""
                ]
                address_string = ", ".join(filter(None, address_components))
                other_info = {
                    "first_name": profile.first_name,
                    "user_location": address_string
                }
            else:
                intro_mssg = bot_vernacular.alt_introductory_message
        else:
            intro_mssg = None

        if state_machine and state_machine.name == 'EVENT':
            bot_question=handle_date_prompt(
                intro_mssg=intro_mssg, profile=profile, company_chats=company_chats, other_info=other_info
            )
            if bot_question is None:
                bot_question = 'I am sorry, I could not understood completely. Could you rephrase this please?'
            if bot_question == '':
                chat_session.current_step += 1
                chat_session.save()
                state_machine = CompanyStateMachine.objects.get(
                    company_bot=company_bot, step=chat_session.current_step
                )
            else:
                translated_message = translate_and_send_message(
                    accumulated_message=bot_question, current_channel_name=channel_name,
                    current_step_number=chat_session.current_step, finish_reason="stop", route=route,
                    company_bot=company_bot
                )
                save_in_company_db(
                    session_id, profile_id, 'AI', bot_question, None, ChatStatus.IN_PROGRESS,
                    translated_message
                )
                return bot_question

        prompt_to_use = get_guided_prompt(
            company_bot=company_bot, system_context=system_context, state_machine=state_machine,
            intro_mssg=intro_mssg, profile=profile
        )

        messages = get_guided_chat(
            company_bot=company_bot, company_chats=company_chats, intro=intro_mssg, other_info=other_info
        )

        response = get_chaupal_tool_call_response(
            system_prompt=prompt_to_use, messages=messages, company_bot=company_bot, session_id=session_id,
            channel_name=channel_name, route=route, profile_id=profile_id, profile=profile
        )
        logger.info('Bedrock Final response: %s', response)

        return response
    except Exception as e:
        print(e)
        logger.error('error: %s', e, exc_info=True)
        traceback.print_exc()
