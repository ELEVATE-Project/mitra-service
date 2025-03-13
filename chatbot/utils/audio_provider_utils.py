from chatbot.models import VoiceProvider, LanguageMapping
from chatbot.translate.ai4Bharat.speech_to_text import ai4bharat_speech_text
from chatbot.translate.ai4Bharat.text_to_speech import ai4bharat_text_speech
from chatbot.translate.ai4Bharat.text_to_text import call_ai4bharat_translation_api
from chatbot.translate.google.google_stt import transcribe_multiple_languages_v2
from chatbot.translate.google.google_translate import translate_text
from chatbot.translate.google.google_tts import google_text_to_speech
from chatbot.translate.openai.openai_stt import transcribe_audio
from shikshalokam_mohini.settings import load_secrets


def text_speech_provider(voice_provider, text, gender, source_language):
    if voice_provider.provider == VoiceProvider.AI4Bharat:
        response = ai4bharat_text_speech(text=text, gender=gender, source_language=source_language)
    elif voice_provider.provider == VoiceProvider.GOOGLE:
        response = google_text_to_speech(
            message=text, language_code=LanguageMapping.get_mapped_language(source_language)
        )
    else:
        return {
            'status': 500,
            'content': "No provider found!"
        }

    return response


def speech_text_provider(voice_provider, base64, audio_format, source_language):
    if voice_provider.provider == VoiceProvider.AI4Bharat:
        response = ai4bharat_speech_text(base64=base64, audio_format=audio_format, source_language=source_language)
    elif voice_provider.provider == VoiceProvider.GOOGLE:
        if source_language == 'en':
            region = "US"
        else:
            region = "IN"

        secret = load_secrets()
        response = transcribe_multiple_languages_v2(
            project_id=secret.get('project_id'), audio_file=base64,
            language_codes=[LanguageMapping.get_mapped_language(source_language, region)]
        )
    elif voice_provider.provider == VoiceProvider.OPENAI_WHISPER:
        response = transcribe_audio(
            base64_audio=base64, audio_format=audio_format, source_language=source_language
        )

    else:
        return {
            'status': 500,
            'content': "No provider found!"
        }
    return response


def text_translate_provider(voice_provider, message_body, target_language, source_language):
    if voice_provider.provider == VoiceProvider.AI4Bharat:
        response = call_ai4bharat_translation_api(
            source_language=source_language, target_language=target_language, message_body=message_body
        )
    elif voice_provider.provider == VoiceProvider.GOOGLE:
        secret = load_secrets()
        response = translate_text(
            project_id=secret.get('project_id'), text=message_body,
            source_language_code=LanguageMapping.get_mapped_language(source_language),
            target_language_code=LanguageMapping.get_mapped_language(target_language)
        )
    else:
        return {
            'status': 500,
            'content': "No provider found!"
        }
    return response
