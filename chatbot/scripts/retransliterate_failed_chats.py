from chatbot.models import CompanyChat, ChatSession, CompanyBot, Voice
from chatbot.utils.transliterate_utils import transliterate_text, get_transliteration_output
import logging

logger = logging.getLogger('django')


def retransliterate_failed_chats():
    company_bot = CompanyBot.objects.filter(route='/shikshalokam_chaupal').first()
    if not company_bot:
        logger.error("CompanyBot with route='/shikshalokam_chaupal' not found")
        return

    session_language_map = {
        s.session: s.language
        for s in ChatSession.objects.exclude(language='en')
    }

    chats = CompanyChat.objects.filter(
        translated_message__icontains='Error during transliteration API call',
        session__in=session_language_map.keys()
    )

    total = chats.count()
    print(f"Found {total} failed transliteration chats...")

    success, failed = 0, 0
    for chat in chats:
        source_language = session_language_map.get(chat.session)
        if not source_language:
            logger.warning(f"No language for session {chat.session}, skipping chat {chat.id}")
            failed += 1
            continue

        voice_provider = Voice.objects.filter(
            company_bot=company_bot, type='Transliterate', language=source_language
        ).first()
        if not voice_provider:
            logger.warning(f"No Voice config for language={source_language}, skipping chat {chat.id}")
            failed += 1
            continue

        response = transliterate_text(
            source_language=source_language,
            target_language='en',
            message_body=chat.message,
            voice_provider=voice_provider
        )

        if response and response.get('status') == 200:
            output = get_transliteration_output(response)
            if output:
                chat.translated_message = output
                chat.save(update_fields=['translated_message'])
                success += 1
            else:
                logger.error(f"Empty transliteration output for chat {chat.id}")
                failed += 1
        else:
            logger.error(f"Transliteration failed for chat {chat.id}: {response}")
            failed += 1

    print(f"Done. Success: {success}, Failed: {failed}")


