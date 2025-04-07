from celery import shared_task
from chatbot.celery_tasks.handle_message import translate_and_send_message
from chatbot.models import CompanyChat, Profile, CompanyBot, ChatSession, LLMProvider, BotVernacular
from chatbot.models.company_models import CompanyStateMachine
from chatbot.utils.chat_utils import get_guided_chat
from chatbot.utils.one_shot_bedrock_tool_call import get_one_shot_bedrock_tool_call_response
from chatbot.utils.one_shot_utils import get_remaining_strands
import logging


logger = logging.getLogger('django')


@shared_task
def get_one_shot_bedrock_response(channel_name, session_id, profile_id, route):
    company_chats = CompanyChat.objects.filter(session=session_id).order_by('created_at')
    chat_session = ChatSession.objects.get(session=session_id)
    profile = Profile.objects.filter(id=profile_id).first()
    if profile:
        company_bot = CompanyBot.objects.get(company=profile.company, route='/oneshot_bot')
    else:
        company_bot = CompanyBot.objects.get(route='/oneshot_bot')

    bot_vernacular = BotVernacular.objects.filter(company_bot=company_bot).first()
    if bot_vernacular:
        if profile and profile.first_name:
            intro_mssg = bot_vernacular.introductory_message
            first_word = intro_mssg.split(" ")[0]
            remaining_message = " ".join(intro_mssg.split(" ")[1:])
            intro_mssg = f"{first_word} {profile.first_name}, {remaining_message}"
        else:
            intro_mssg = None
    else:
        intro_mssg = None

    messages = get_guided_chat(
        company_bot=company_bot, company_chats=company_chats, intro=intro_mssg
    )

    if not chat_session.session_context:
        chat_session.session_context = {}
    remaining_stages = chat_session.session_context.get('remaining_stages')
    print("Leng of msg: ", len(messages))
    if not remaining_stages and (
            (intro_mssg is None and len(messages) < 2) or
            (intro_mssg is not None and len(messages) <= 3)
    ):
        remaining_stages_response = get_remaining_strands(
            messages=messages, company_chats=company_chats, oneshot_bot=company_bot,
            profile=profile, intro=intro_mssg
        )
        if remaining_stages_response and remaining_stages_response.get('error'):
            error_msg = remaining_stages_response.get('error')
            logger.info(f"Sending message: %s", error_msg)
            print("Sending message: ", error_msg)
            translated_message = translate_and_send_message(
                accumulated_message=error_msg, current_channel_name=channel_name,
                current_step_number=chat_session.current_step, finish_reason="stop", route=route,
                company_bot=company_bot
            )
            return translated_message
        remaining_stages = remaining_stages_response.get('remaining_stages', [])
        print("remaining_stages: ", remaining_stages)
        if remaining_stages and isinstance(remaining_stages, str):
            remaining_stages = []
        remaining_stages.append('APPRECIATION')
        chat_session.session_context['remaining_stages'] = remaining_stages
        chat_session.save()
        print("Remaining Strands: ", remaining_stages)

    current_stage_name = remaining_stages[0]

    try:
        state_machine = CompanyStateMachine.objects.get(company_bot=company_bot, name=current_stage_name)
        chat_session.current_step = state_machine.step
        chat_session.save()
    except Exception as e:
        print("Error: ", e)
        return

    prompt_to_use = get_onestep_prompt(
        company_bot=company_bot, state_machine=state_machine
    )

    response = get_one_shot_bedrock_tool_call_response(
        system_prompt=prompt_to_use, messages=messages, company_bot=company_bot, session_id=session_id,
        channel_name=channel_name, route=route, profile_id=profile_id, remaining_stages=remaining_stages
    )

    return response


def get_onestep_prompt(company_bot, state_machine):
    prompt_to_use=[]
    if company_bot.provider == LLMProvider.BEDROCK_CONVERSE:
        prompt_to_use = [
            {
                'text': company_bot.context
            },
            {
                'text': f"""
                    {state_machine.context}

                    Completion Criteria:
                    {state_machine.completion_criteria}
                    """
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
                    company_bot.context,
                    state_machine.context,
                    state_machine.completion_criteria
                )
            }
        ]

    return prompt_to_use
