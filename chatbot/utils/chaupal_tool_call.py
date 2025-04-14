from channels.layers import get_channel_layer
from chatbot.celery_tasks.common_chat_tasks import save_in_company_db
from chatbot.celery_tasks.handle_message import translate_and_send_message
from chatbot.llm_models.llm_script import handle_bedrock_model, handle_openai_model
from chatbot.models import ChatSession, ChatStatus, LLMProvider
from chatbot.models.company_models import CompanyStateMachine
import logging

from chatbot.utils.chaupal_question import get_chaupal_challenge_response, get_chaupal_solution_response
from chatbot.utils.shiksha_chaupal.checker_utils import prepare_missing_stage_questions

logger = logging.getLogger('django')
channel_layer = get_channel_layer()


def get_chaupal_tool_call_response(
        system_prompt, messages, company_bot, session_id, channel_name, route, profile_id, profile
):

    chat_session = ChatSession.objects.get(session=session_id)
    current_step = chat_session.current_step
    chunks = []

    response = None
    if company_bot.provider == LLMProvider.BEDROCK_CONVERSE:
        try:
            response = handle_bedrock_model(
                system_prompt=system_prompt, messages=messages, model_name=company_bot.llm_model,
                temperature=company_bot.bot_temperature, max_token=company_bot.max_token, company_bot=company_bot
            )
        except Exception as e:
            logger.error(f"Got Error: %s", e)
            print(f"Got Error: {e}")
            response = None
    elif company_bot.provider == LLMProvider.OPENAI:
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_state_information",
                    "description": "Get the information of the state you want to be in.",
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
        ]
        response = handle_openai_model(
            system_prompt=system_prompt, messages=messages, model_name=company_bot.llm_model,
            temperature=company_bot.bot_temperature, max_token=company_bot.max_token,
            tools=tools, tool_choice='auto', is_json_response=False
        )

    print("response_body bedrock: ", response)
    if response is None:
        response = 'I am sorry, I could not understood completely. Could you rephrase this please?'

    print("Response: ", response)
    is_function_call = False
    if isinstance(response, dict):
        is_function_call = True
    elif isinstance(response, str):
        if 'get_state_information' in response:
            is_function_call = True
    print("is_function_call: ", is_function_call)
    if is_function_call:
        bot_question = ""
        print("its func call")
        extra_question = None
        chat_session.current_step += 1
        chat_session.save()
        state_machine = CompanyStateMachine.objects.get(company_bot=company_bot, step=chat_session.current_step)
        print("Statemachine we using: ", state_machine.name, " with step: ", state_machine.step)
        if state_machine and state_machine.name == "CHECKER":
            checker_response = prepare_missing_stage_questions(
                company_bot=company_bot, state_machine=state_machine, messages=messages, profile=profile
            )
            print("checker_response: ", checker_response)
            chat_session.session_context = checker_response
            chat_session.current_step += 1
            chat_session.save()
            state_machine = CompanyStateMachine.objects.get(company_bot=company_bot, step=chat_session.current_step)
            extra_question = prepare_missing_stage_questions(
                company_bot=company_bot, state_machine=state_machine, messages=messages,
                extra_data=checker_response
            )
        if extra_question:
            if isinstance(extra_question, dict):
                is_function_call = True
            elif isinstance(response, str):
                if 'get_state_information' in response:
                    is_function_call = True
            else:
                is_function_call = False
                bot_question = extra_question
            if is_function_call:
                chat_session.current_step += 1
                chat_session.save()
                state_machine = CompanyStateMachine.objects.get(
                    company_bot=company_bot, step=chat_session.current_step
                )
                bot_question = state_machine.bot_question
        else:
            bot_question = state_machine.bot_question

        if state_machine.name == 'CHALLENGES':
            challenge_res = get_chaupal_challenge_response(messages=messages)
            if challenge_res and isinstance(challenge_res, str):
                bot_question = challenge_res
            else:
                bot_question = 'I am sorry, I could not understood completely. Could you rephrase this please?'
        if state_machine.name == 'SOLUTIONS':
            solution_res = get_chaupal_solution_response(messages=messages)
            if solution_res and isinstance(solution_res, str):
                bot_question = solution_res
            else:
                bot_question = 'I am sorry, I could not understood completely. Could you rephrase this please?'

        print("In function call: so asking bot question as: ", bot_question)
        translated_message = translate_and_send_message(
            accumulated_message=bot_question, current_channel_name=channel_name,
            current_step_number=chat_session.current_step, finish_reason="stop", route=route,
            company_bot=company_bot
        )

        name_machine = state_machine.name
        print("name_machine: ", name_machine)
        if state_machine.name == "APPRECIATION":
            chat_status = ChatStatus.COMPLETED
        else:
            chat_status = ChatStatus.IN_PROGRESS

        save_in_company_db(
            session_id, profile_id, 'AI', bot_question, chunks, chat_status, translated_message
        )
        return response
    else:
        print("its not a  func call")
        translated_message = translate_and_send_message(
            accumulated_message=response, current_channel_name=channel_name,
            current_step_number=current_step, finish_reason="stop", route=route,
            company_bot=company_bot
        )
        save_in_company_db(
            session_id, profile_id, 'AI', response, chunks, ChatStatus.IN_PROGRESS, translated_message
        )

        return response
