import traceback
from celery import shared_task
from chatbot.models import CompanyChat, Profile, CompanyBot, ChatSession, LLMProvider, BotVernacular
from chatbot.models.company_models import CompanyStateMachine
from chatbot.utils.bedrock_tool_call import get_bedrock_tool_call_response
from chatbot.utils.chat_utils import get_guided_chat
import logging


logger = logging.getLogger('django')


@shared_task
def get_shikshalokam_bedrock_response(channel_name, session_id, profile_id, route):
    try:
        company_chats = CompanyChat.objects.filter(session=session_id).order_by('created_at')
        print(session_id)
        chat_session = ChatSession.objects.filter(session=session_id).first()
        profile = Profile.objects.get(id=profile_id)
        company_bot = CompanyBot.objects.get(company=profile.company, route='/')
        if company_chats and len(company_chats) < 2:
            chat_session.current_step += 1
            chat_session.save()
        state_machine = CompanyStateMachine.objects.get(company_bot=company_bot, step=chat_session.current_step)
        system_context = company_bot.context

        prompt_to_use = get_guided_prompt(
            company_bot=company_bot, system_context=system_context, state_machine=state_machine
        )
        bot_vernacular = BotVernacular.objects.filter(company_bot=company_bot).first()
        if bot_vernacular:
            intro_mssg = bot_vernacular.introductory_message
        else:
            intro_mssg = None
        messages = get_guided_chat(
            company_bot=company_bot, company_chats=company_chats, intro=intro_mssg
        )

        response = get_bedrock_tool_call_response(
            system_prompt=prompt_to_use, messages=messages, company_bot=company_bot, session_id=session_id,
            channel_name=channel_name, route=route, profile_id=profile_id
        )
        logger.info('Bedrock Final response: %s', response)

        return response
    except Exception as e:
        print(e)
        logger.error('error: %s', e, exc_info=True)
        traceback.print_exc()


def get_guided_prompt(company_bot, system_context, state_machine):
    prompt_to_use=[]
    if company_bot.provider == LLMProvider.BEDROCK_CONVERSE:
        prompt_to_use = [
            {
                'text': system_context
            },
            {
                'text': """
                {}

                Completion Criteria:
                {}
                """.format(state_machine.context, state_machine.completion_criteria)
            },
            {
                'text': company_bot.tool_context
            }
        ]
    elif company_bot.provider == LLMProvider.OPENAI:
        prompt_to_use = [
            {
                'role': 'system',
                'content': """{}

                            {}

                            Completion Criteria:
                            {}""".format(
                    system_context,
                    state_machine.context,
                    state_machine.completion_criteria
                )
            }
        ]

    return prompt_to_use

