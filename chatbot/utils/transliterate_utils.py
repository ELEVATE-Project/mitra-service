from chatbot.models import VoiceProvider
from chatbot.translate.ai4Bharat.transliterate import call_ai4bharat_transliterate_api


def transliterate_text(voice_provider, source_language, target_language, message_body, is_sentence=False):
    if voice_provider.provider == VoiceProvider.AI4Bharat:
        response = call_ai4bharat_transliterate_api(
            source_language=source_language, target_language=target_language, message_body=message_body,
            is_sentence=is_sentence
        )
    else:
        return {
            'status': 500,
            'content': "No provider found!"
        }
    return response


def get_transliteration_output(data):
    if data and isinstance(data, dict):
        data = data.get('content', [])
    if data and isinstance(data, list) and len(data) > 0:
        return data[0]

    return None
