import base64
import logging
import os

import requests

logger = logging.getLogger("django")

SL_LLM_BASE_URL = os.getenv("SL_LLM_BASE_URL", "")


def sl_speech_to_text(base64_audio_file: str, source_language: str, audio_format: str, voice_provider) -> dict:
    try:
        audio_bytes = base64.b64decode(base64_audio_file)
        filename = f"audio.{audio_format}"
        mime_type = f"audio/{audio_format}"

        other = voice_provider.other_params if voice_provider and voice_provider.other_params else {}
        request_timeout = other.get("request_timeout", 60)
        try:
            request_timeout = float(request_timeout)
        except Exception:
            request_timeout = 60

        response = requests.post(
            url=f"{SL_LLM_BASE_URL}/transcribe",
            files={"audio": (filename, audio_bytes, mime_type)},
            data={"source_lang": source_language},
            timeout=request_timeout,
        )
        response.raise_for_status()
        return {"status": 200, "content": response.json().get("text", "")}
    except Exception as e:
        logger.error("ShikshaLokam STT error: %s", e)
        return {"status": 500, "content": str(e)}
