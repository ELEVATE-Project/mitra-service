import base64
import logging
import os

import boto3

from chatbot.models import CompanyBot, Voice, VoiceType
from chatbot.models.bot_vernacular_model import BotVernacular
from chatbot.models.company_models import CompanyStateMachine
from chatbot.utils.audio_provider_utils import text_speech_provider, text_translate_provider
from shikshalokam_mohini.celery_config import app

logger = logging.getLogger("django")

S3_MEDIA_URL = os.getenv("S3_MEDIA_URL", "")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "")
AWS_REGION = os.getenv("AWS_REGION", "")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")


def _upload_audio_to_s3(audio_bytes, company_bot_id, state_machine_id, lang, audio_format):
    """Upload audio bytes to S3, return full URL or None."""
    try:
        key = f"state_machine_audio/{company_bot_id}/{state_machine_id}/{lang}.{audio_format}"
        s3 = boto3.client(
            "s3",
            region_name=AWS_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        )
        s3.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=key,
            Body=audio_bytes,
            ContentType=f"audio/{audio_format}",
        )
        return f"{S3_MEDIA_URL}{key}"
    except Exception as e:
        logger.info(
            f"generate_translations: S3 upload failed for sm={state_machine_id} lang: {e}"
        )
        return None


@app.task
def generate_state_machine_translations(company_bot_id, language=None):
    """
    Generate cached translations + TTS audio for all CompanyStateMachines on a bot.
    If language is provided, only process that language (used for new-language auto-trigger).
    """
    try:
        company_bot = CompanyBot.objects.get(id=company_bot_id)
    except CompanyBot.DoesNotExist:
        logger.info(f"generate_translations: CompanyBot id={company_bot_id} not found")
        return

    ttt_voices = Voice.objects.filter(
        company_bot=company_bot, type=VoiceType.TextToText
    )
    tts_voices = Voice.objects.filter(
        company_bot=company_bot, type=VoiceType.TextToSpeech
    )

    if language:
        languages = [language]
    else:
        languages = list(ttt_voices.values_list("language", flat=True))

    tts_voice_map = {v.language: v for v in tts_voices}

    state_machines = CompanyStateMachine.objects.filter(company_bot=company_bot)

    bot_vernaculars = list(BotVernacular.objects.values("language", "alt_introductory_message").filter(company_bot=company_bot))

    vernacular_map = {}
    vernacular_lang_counts = {}
    for v in bot_vernaculars:
        vernacular_lang_counts[v["language"]] = vernacular_lang_counts.get(v["language"], 0) + 1
        if v["language"] not in vernacular_map and v["alt_introductory_message"]:
            vernacular_map[v["language"]] = v["alt_introductory_message"]
    for lang, count in vernacular_lang_counts.items():
        if count > 1:
            logger.info(
                f"generate_translations: multiple BotVernacular rows for company_bot={company_bot_id} lang={lang}, using first"
            )

    for sm in state_machines:
        if not sm.bot_question and sm.step != 1:
            continue

        cached = dict(sm.translations or {})

        for lang in languages:
            lang_data = dict(cached.get(lang, {}))

            if sm.step == 1:
                lang_data.pop("text", None)
                vernacular_text = vernacular_map.get(lang)

                if not vernacular_text:
                    continue
                tts_voice = tts_voice_map.get(lang)
                try:
                    tts_result = text_speech_provider(
                        company_bot=company_bot,
                        text=vernacular_text,
                        source_language=lang,
                    )
                    if tts_result and tts_result.get("status") == 200:
                        audio_b64 = tts_result["content"]
                        if ";base64," in audio_b64:
                            audio_b64 = audio_b64.split(";base64,", 1)[1]
                        audio_bytes = base64.b64decode(audio_b64)
                        audio_format = "wav"
                        if tts_voice and tts_voice.other_params:
                            audio_format = tts_voice.other_params.get(
                                "output_audio_codec", "wav"
                            )
                        url = _upload_audio_to_s3(
                            audio_bytes, company_bot_id, sm.id, lang, audio_format
                        )
                        if url:
                            lang_data["audio_s3"] = url
                except Exception as e:
                    logger.info(f"generate_translations: TTS failed sm={sm.id} lang={lang}: {e}")

                if lang_data:
                    cached[lang] = lang_data
                else:
                    cached.pop(lang, None)
                continue

            # Text translation
            if lang != "en":
                try:
                    result = text_translate_provider(
                        message_body=sm.bot_question,
                        target_language=lang,
                        source_language="en",
                        company_bot=company_bot,
                    )
                    if result and result.get("status") == 200:
                        lang_data["text"] = result["content"]
                except Exception as e:
                    logger.info(f"generate_translations: text translation failed sm={sm.id} lang={lang}: {e}")

            # TTS
            tts_voice = tts_voice_map.get(lang)
            try:
                tts_text = lang_data.get("text") or sm.bot_question
                tts_result = text_speech_provider(
                    company_bot=company_bot,
                    text=tts_text,
                    source_language=lang,
                )
                if tts_result and tts_result.get("status") == 200:
                    audio_b64 = tts_result["content"]
                    # Strip data URI prefix if present
                    if ";base64," in audio_b64:
                        audio_b64 = audio_b64.split(";base64,", 1)[1]
                    audio_bytes = base64.b64decode(audio_b64)
                    audio_format = "wav"
                    if tts_voice and tts_voice.other_params:
                        audio_format = tts_voice.other_params.get(
                            "output_audio_codec", "wav"
                        )
                    url = _upload_audio_to_s3(
                        audio_bytes, company_bot_id, sm.id, lang, audio_format
                    )
                    if url:
                        lang_data["audio_s3"] = url
            except Exception as e:
                logger.info(f"generate_translations: TTS failed sm={sm.id} lang={lang}: {e}")

            if lang_data:
                cached[lang] = lang_data

        CompanyStateMachine.objects.filter(pk=sm.pk).update(translations=cached)
        logger.info(f"generate_translations: updated sm={sm.id} languages={languages}")
