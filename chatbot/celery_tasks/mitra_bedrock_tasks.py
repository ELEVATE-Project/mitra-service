import traceback
from celery import shared_task
from chatbot.celery_tasks.common_chat_tasks import save_in_company_db
from chatbot.celery_tasks.handle_message import translate_and_send_message
from chatbot.llm_models.llm_script import handle_bedrock_model
from chatbot.models import CompanyChat, Profile, CompanyBot, ChatStatus
from chatbot.translate.ai4Bharat.text_to_text import call_ai4bharat_translation_api


@shared_task
def get_mitra_bedrock_response(channel_name, session_id, profile_id, route):
    print(session_id)
    try:
        company_chats = CompanyChat.objects.filter(session=session_id).order_by('created_at')
        profile = Profile.objects.get(id=profile_id)
        ai_user = Profile.objects.get(id=1)
        company_bot = CompanyBot.objects.get(company=profile.company, route='/mitra-create')
        system_context = company_bot.context

        prompt_to_use = [
            {
                'text': system_context.replace("{first_name}", profile.first_name)
            }
        ]

        messages=[]
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

        response = handle_bedrock_model(
            system_prompt=prompt_to_use, messages=messages
        )
        print("response_body bedrock: ", response)

        if response:
            message = response.get("message", "")
            problem_statement = response.get("problem_statement", "")

            problem_statement = call_ai4bharat_translation_api(
                message_body=problem_statement, target_language=route,
                source_language='en'
            )

            extra_content = {
                "problem_statement": problem_statement,
                "should_move_forward": response.get("should_move_forward", False),
                "validation": response.get("validation", "")
            }

            translated_message = translate_and_send_message(
                accumulated_message=message, current_channel_name=channel_name,
                current_step_number=1, finish_reason="stop", route=route,
                extra_content=extra_content
            )
            save_in_company_db(
                session_id, profile_id, 'AI', response, None, ChatStatus.IN_PROGRESS,
                translated_message
            )
        return response
    except Exception as e:
        print(e)
        traceback.print_exc()
