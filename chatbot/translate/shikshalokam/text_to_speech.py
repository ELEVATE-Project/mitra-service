import base64
import logging
import os

import requests

logger = logging.getLogger("django")

SL_LLM_BASE_URL = os.getenv("SL_LLM_BASE_URL", "")


def sl_text_to_speech(text: str, source_language: str, voice_provider) -> dict:
    try:
        response = requests.post(
            url=f"{SL_LLM_BASE_URL}/tts",
            json={"text": text, "target_lang": source_language},
            timeout=60,
        )
        response.raise_for_status()
        audio_base64 = base64.b64encode(response.content).decode("utf-8")
        return {"status": 200, "content": audio_base64}
    except Exception as e:
        logger.error("ShikshaLokam TTS error: %s", e)
        return {"status": 500, "content": str(e)}
