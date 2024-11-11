from channels.layers import get_channel_layer
from chatbot.celery_tasks.common_chat_tasks import save_in_company_db
from chatbot.celery_tasks.handle_message import translate_and_send_message
from chatbot.llm_models.llm_script import handle_bedrock_model
from chatbot.models import ChatSession, ChatStatus, CompanyChat
from chatbot.models.company_models import CompanyStateMachine


channel_layer = get_channel_layer()


def get_bedrock_tool_call_response(system_prompt, messages, company_bot, session_id, channel_name, route, profile_id):
    tool = {
        "toolConfig": {
            "tools": [
                {
                    "toolSpec": {
                        "name": "get_state_information",
                        "description": "Get the information of the state you want to be in.",
                        "inputSchema": {
                            "json": {
                                "type": "object",
                                "properties": {
                                    "state_name": {
                                        "type": "string",
                                        "description": "Name of the next state provided in the context."
                                    }
                                },
                                "required": [
                                    "state_name"
                                ]
                            }
                        }
                    }
                }
            ]
        }
    }

    chat_session = ChatSession.objects.get(session=session_id)
    current_step = chat_session.current_step
    company_chat = CompanyChat.objects.filter(session=session_id)
    print("Length: ", len(company_chat))
    chunks = []

    if company_chat and len(company_chat)<2:
        chat_session.current_step += 1
        chat_session.save()
        state_machine = CompanyStateMachine.objects.get(company_bot=company_bot, step=chat_session.current_step)
        bot_question = state_machine.bot_question

        translated_message = translate_and_send_message(
            accumulated_message=bot_question, current_channel_name=channel_name,
            current_step_number=chat_session.current_step, finish_reason="stop", route=route
        )

        save_in_company_db(
            session_id, profile_id, 'AI', bot_question, chunks, ChatStatus.IN_PROGRESS, translated_message
        )
        print("asking first bot_question: ", bot_question)
        return bot_question


    response = handle_bedrock_model(
        system_prompt=system_prompt, messages=messages, tools=tool
    )
    print("response_body bedrock: ", response)


    print("Response: ", response)
    is_function_call = False
    if isinstance(response, dict):
        tool_use_id = response.get('toolUseId', None)
        if tool_use_id:
            is_function_call = True
    print("is_function_call: ", is_function_call)


    if is_function_call:
        chat_session.current_step += 1
        chat_session.save()
        state_machine = CompanyStateMachine.objects.get(company_bot=company_bot, step=chat_session.current_step)
        bot_question = state_machine.bot_question

        translated_message = translate_and_send_message(
            accumulated_message=bot_question, current_channel_name=channel_name,
            current_step_number=chat_session.current_step, finish_reason="stop", route=route
        )

        save_in_company_db(
            session_id, profile_id, 'AI', bot_question, chunks, ChatStatus.IN_PROGRESS, translated_message
        )
        return response
    else:
        translated_message = translate_and_send_message(
            accumulated_message=response, current_channel_name=channel_name,
            current_step_number=current_step, finish_reason="stop", route=route
        )
        save_in_company_db(
            session_id, profile_id, 'AI', response, chunks, ChatStatus.IN_PROGRESS, translated_message
        )

        return response
