from celery import shared_task
from chatbot.models import CompanyChat, Profile, CompanyBot, ChatSession
from chatbot.models.company_models import CompanyStateMachine
from chatbot.utils.bedrock_tool_call import get_bedrock_tool_call_response


@shared_task
def get_shikshalokam_bedrock_response(channel_name, session_id, profile_id, route):
    company_chats = CompanyChat.objects.filter(session=session_id).order_by('created_at')
    print(session_id)
    chat_session = ChatSession.objects.get(session=session_id)
    profile = Profile.objects.get(id=profile_id)
    ai_user = Profile.objects.get(id=1)
    company_bot = CompanyBot.objects.get(company=profile.company, route='/')
    state_machine = CompanyStateMachine.objects.get(company_bot=company_bot, step=chat_session.current_step)
    system_context = company_bot.context
    introductory_message = company_bot.introductory_message

    prompt_to_use = [
        {
            # Use 'text' key only for system prompts
            'text': system_context
        },
        {
            'text': """
            {}

            Completion Criteria:
            {}
            """.format(state_machine.context, state_machine.completion_criteria)
            # Use 'text' key for system instructions
        },
        {
            'text': """
            Given the following functions, please respond with a JSON for a function call with its proper arguments 
            that best answers the given prompt.
            
            Respond strictly in the format:
            {"name": "function_name", "parameters": {"argument_name": "argument_value"}}. 
            Do not use variables, placeholders, or additional conversational responses.
            
            If the next state is provided in the context (e.g., `state_name`), always respond with a function call to transition to the specified state. Do not engage in further dialog or ask follow-up questions in this step.
            
            Here is the function definition:
            
            {
                "type": "function",
                "function": {
                    "name": "get_state_information",
                    "description": "Get the information of the state you want to be in",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "state_name": {
                                "type": "string",
                                "description": "Name of the next state provided in the context."
                            }
                        },
                        "required": ["state_name"]
                    }
                }
            }

            """
        }
    ]

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

    response = get_bedrock_tool_call_response(
        system_prompt=prompt_to_use, messages=messages, company_bot=company_bot, session_id=session_id,
        channel_name=channel_name, route=route, profile_id=profile_id
    )

    return response
