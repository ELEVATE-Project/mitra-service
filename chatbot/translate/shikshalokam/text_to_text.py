import logging
import os

import requests

logger = logging.getLogger("django")

SL_LLM_BASE_URL = os.getenv("SL_LLM_BASE_URL", "")


def sl_translate(message_body: str, source_language: str, target_language: str, voice_provider) -> dict:
    try:
        other = voice_provider.other_params if voice_provider and voice_provider.other_params else {}
        request_timeout = other.get("request_timeout", 60)
        try:
            request_timeout = float(request_timeout)
        except Exception:
            request_timeout = 60

        response = requests.post(
            url=f"{SL_LLM_BASE_URL}/translate",
            json={
                "text": message_body,
                "source_lang": source_language,
                "target_lang": target_language,
            },
            timeout=request_timeout,
        )
        response.raise_for_status()
        return {"status": 200, "content": response.json().get("translation", "")}
    except Exception as e:
        logger.error("ShikshaLokam translate error: %s", e)
        return {"status": 500, "content": str(e)}
