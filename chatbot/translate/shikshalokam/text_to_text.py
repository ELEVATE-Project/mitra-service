import logging
import os

import requests

logger = logging.getLogger("django")

SL_LLM_BASE_URL = os.getenv("SL_LLM_BASE_URL", "")


def sl_translate(message_body: str, source_language: str, target_language: str, voice_provider) -> dict:
    try:
        response = requests.post(
            url=f"{SL_LLM_BASE_URL}/translate",
            json={
                "text": message_body,
                "source_lang": source_language,
                "target_lang": target_language,
            },
            timeout=60,
        )
        response.raise_for_status()
        return {"status": 200, "content": response.json().get("translation", "")}
    except Exception as e:
        logger.error("ShikshaLokam translate error: %s", e)
        return {"status": 500, "content": str(e)}
