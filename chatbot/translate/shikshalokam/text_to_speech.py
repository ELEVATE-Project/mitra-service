import base64
import logging
import os

import requests

logger = logging.getLogger("django")

SL_LLM_BASE_URL = os.getenv("SL_LLM_BASE_URL", "")


def sl_text_to_speech(text: str, source_language: str, voice_provider) -> dict:
    try:
        other = voice_provider.other_params if voice_provider and voice_provider.other_params else {}
        request_timeout = other.get("request_timeout", 60)
        try:
            request_timeout = float(request_timeout)
        except Exception:
            request_timeout = 60

        response = requests.post(
            url=f"{SL_LLM_BASE_URL}/tts",
            json={"text": text, "target_lang": source_language},
            timeout=request_timeout,
        )
        response.raise_for_status()
        audio_base64 = base64.b64encode(response.content).decode("utf-8")
        return {"status": 200, "content": audio_base64}
    except Exception as e:
        logger.error("ShikshaLokam TTS error: %s", e, exc_info=True)
        return {"status": 500, "content": str(e)}
