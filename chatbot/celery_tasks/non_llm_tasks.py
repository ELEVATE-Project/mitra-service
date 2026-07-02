import logging

from shikshalokam_mohini.celery_config import app
from chatbot.models import CompanyChat, ChatSession
from chatbot.utils.audio_provider_utils import text_translate_provider

logger = logging.getLogger('django')


@app.task
def translate_user_answer(company_chat_id, source_language='en', target_language='en'):
    """
    Async task: translate a user's NON_LLM answer from vernacular to English.
    Updates CompanyChat.translated_message with the result.
    """
    if source_language == target_language:
        logger.info(f"translate_user_answer: source==target ({source_language}), skipping for chat_id={company_chat_id}")
        return

    try:
        company_chat = CompanyChat.objects.get(id=company_chat_id)
    except CompanyChat.DoesNotExist:
        logger.info(f"translate_user_answer: CompanyChat id={company_chat_id} not found")
        return

    try:
        chat_session = ChatSession.objects.select_related('company_bot').get(session=company_chat.session)
        company_bot = chat_session.company_bot
    except ChatSession.DoesNotExist:
        logger.info(f"translate_user_answer: ChatSession not found for session={company_chat.session}")
        return

    if not company_bot:
        logger.info(f"translate_user_answer: no company_bot on session={company_chat.session}")
        return

    try:
        result = text_translate_provider(
            message_body=company_chat.message,
            target_language=target_language,
            source_language=source_language,
            company_bot=company_bot,
        )
        if result and result.get('status') == 200:
            company_chat.translated_message = result.get('content')
            company_chat.save(update_fields=['translated_message'])
            logger.info(f"translate_user_answer: translated chat_id={company_chat_id} from {source_language} to {target_language}")
        else:
            logger.info(f"translate_user_answer: translation failed for chat_id={company_chat_id}: {result}")
    except Exception as e:
        logger.info(f"translate_user_answer: exception for chat_id={company_chat_id}: {e}")
