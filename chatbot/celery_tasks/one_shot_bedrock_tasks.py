from celery import shared_task
from chatbot.models import CompanyChat, Profile, CompanyBot, ChatSession
from chatbot.models.company_models import CompanyStateMachine
from chatbot.utils.one_shot_bedrock_tool_call import get_one_shot_bedrock_tool_call_response
from chatbot.utils.one_shot_utils import get_remaining_strands


@shared_task
def get_one_shot_bedrock_response(channel_name, session_id, profile_id, route):
    company_chats = CompanyChat.objects.filter(session=session_id).order_by('created_at')
    chat_session = ChatSession.objects.get(session=session_id)
    profile = Profile.objects.get(id=profile_id)
    ai_user = Profile.objects.get(id=1)
    company_bot = CompanyBot.objects.get(company=profile.company, route='/oneshot_bot')

    messages=[]
    # Bedrock wants user to initiate message first so skipping into mssg
    for chat in company_chats:
        if chat.receiver == ai_user:
            user_message = chat.message
            if chat.translated_message is not None and chat.translated_message != '':
                user_message = chat.translated_message
            messages.append({
                'role': 'user',
                'content': [{'text': user_message}]
            })
        else:
            messages.append({
                'role': 'assistant',
                "content": [{'text': chat.message}]
            })

    if not chat_session.session_context:
        chat_session.session_context = {}
    remaining_stages = chat_session.session_context.get('remaining_stages')

    if not remaining_stages and len(messages) < 2:
        remaining_stages_response = get_remaining_strands(messages=messages)
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

    response = get_one_shot_bedrock_tool_call_response(
        system_prompt=prompt_to_use, messages=messages, company_bot=company_bot, session_id=session_id,
        channel_name=channel_name, route=route, profile_id=profile_id, remaining_stages=remaining_stages
    )

    return response
