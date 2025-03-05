from celery import shared_task
from chatbot.models import CompanyChat, Profile, CompanyBot, ChatSession, LLMProvider
from chatbot.models.company_models import CompanyStateMachine
from chatbot.utils.chat_utils import get_guided_chat
from chatbot.utils.one_shot_bedrock_tool_call import get_one_shot_bedrock_tool_call_response
from chatbot.utils.one_shot_utils import get_remaining_strands


@shared_task
def get_one_shot_bedrock_response(channel_name, session_id, profile_id, route):
    company_chats = CompanyChat.objects.filter(session=session_id).order_by('created_at')
    chat_session = ChatSession.objects.get(session=session_id)
    profile = Profile.objects.get(id=profile_id)
    company_bot = CompanyBot.objects.get(company=profile.company, route='/oneshot_bot')

    messages = get_guided_chat(
        company_bot=company_bot, company_chats=company_chats
    )

    if not chat_session.session_context:
        chat_session.session_context = {}
    remaining_stages = chat_session.session_context.get('remaining_stages')

    if not remaining_stages and len(messages) < 2:
        remaining_stages_response = get_remaining_strands(
            messages=messages, company_chats=company_chats, oneshot_bot=company_bot
        )
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
