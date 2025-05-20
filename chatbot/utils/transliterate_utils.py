from chatbot.models import VoiceProvider
from chatbot.translate.ai4Bharat.transliterate import call_ai4bharat_transliterate_api


def transliterate_text(voice_provider, source_language, target_language, message_body):
    if voice_provider.provider == VoiceProvider.AI4Bharat:
        response = call_ai4bharat_transliterate_api(
            source_language=source_language, target_language=target_language, message_body=message_body
        )
    else:
        return {
            'status': 500,
            'content': "No provider found!"
        }
    return response
