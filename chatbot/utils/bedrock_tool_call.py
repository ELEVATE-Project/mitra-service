from channels.layers import get_channel_layer
from chatbot.celery_tasks.common_chat_tasks import save_in_company_db
from chatbot.celery_tasks.handle_message import translate_and_send_message
from chatbot.llm_models.llm_script import handle_bedrock_model
from chatbot.models import ChatSession, ChatStatus, CompanyChat
from chatbot.models.company_models import CompanyStateMachine


channel_layer = get_channel_layer()


def get_bedrock_tool_call_response(
        system_prompt, messages, company_bot, session_id, channel_name, route, profile_id,
        user_problem_statement
):

    chat_session = ChatSession.objects.get(session=session_id)
    current_step = chat_session.current_step
    company_chat = CompanyChat.objects.filter(session=session_id)
    print("Length: ", len(company_chat))
    chunks = []

    if user_problem_statement:
        chat_session.current_step += 2
        chat_session.save()
        state_machine = CompanyStateMachine.objects.get(company_bot=company_bot, step=chat_session.current_step)
        pre_context = company_bot.pre_context
        if pre_context:
            pre_context = pre_context.format(problem_statement=user_problem_statement)
        bot_question = pre_context + " " + state_machine.bot_question

        translated_message = translate_and_send_message(
            accumulated_message=bot_question, current_channel_name=channel_name,
            current_step_number=chat_session.current_step, finish_reason="stop", route=route
        )

        save_in_company_db(
            session_id, profile_id, 'AI', bot_question, chunks, ChatStatus.IN_PROGRESS, translated_message
        )
        print("skipping stages bot_question: ", bot_question)
        return bot_question
    elif company_chat and len(company_chat)<2:
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
        system_prompt=system_prompt, messages=messages
    )
    print("response_body bedrock: ", response)


    is_function_call = False
    if isinstance(response, dict):
        tool_use_id = response.get('toolUseId', None)
        if tool_use_id:
            is_function_call = True
    print("is_function_call: ", is_function_call)


    if is_function_call:
        print("its func call")
        chat_session.current_step += 1
        chat_session.save()
        state_machine = CompanyStateMachine.objects.get(company_bot=company_bot, step=chat_session.current_step)
        bot_question = state_machine.bot_question

        translated_message = translate_and_send_message(
            accumulated_message=bot_question, current_channel_name=channel_name,
            current_step_number=chat_session.current_step, finish_reason="stop", route=route
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
            current_step_number=current_step, finish_reason="stop", route=route
        )
        save_in_company_db(
            session_id, profile_id, 'AI', response, chunks, ChatStatus.IN_PROGRESS, translated_message
        )

        return response
