import traceback
from celery import shared_task
from chatbot.models import CompanyChat, Profile, CompanyBot, ChatSession, LLMProvider, BotVernacular
from chatbot.models.company_models import CompanyStateMachine
from chatbot.utils.chat_utils import get_guided_chat
import logging
from jinja2 import Template
from chatbot.utils.chaupal_tool_call import get_chaupal_tool_call_response

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
                other_info = {
                    "first_name": profile.first_name
                }
            else:
                intro_mssg = bot_vernacular.alt_introductory_message
        else:
            intro_mssg = None

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


def get_guided_prompt(company_bot, system_context, state_machine, intro_mssg=None, profile=None):
    prompt_to_use=[]
    profile_addresses=None
    if profile and profile.first_name:
        profile_addresses = profile.profile_address.all().first()
    address_components = [
        profile_addresses.district if profile_addresses and profile_addresses.district else "",
        profile_addresses.block if profile_addresses and profile_addresses.block else "",
        profile_addresses.state if profile_addresses and profile_addresses.state else ""
    ]
    address_string = ", ".join(filter(None, address_components))


    state_machine_context = state_machine.context
    if intro_mssg:
        context_data = {
            "intro_message": intro_mssg,
            "user_location": address_string
        }
        template = Template(state_machine_context)
        state_machine_context = template.render(context_data)

    if company_bot.provider == LLMProvider.BEDROCK_CONVERSE:
        prompt_to_use = [
            {
                'text': system_context
            },
            {
                'text': """
                {}

                Completion Criteria for function calling:
                {}
                """.format(state_machine_context, state_machine.completion_criteria)
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
                    state_machine_context,
                    state_machine.completion_criteria
                )
            }
        ]

    return prompt_to_use

