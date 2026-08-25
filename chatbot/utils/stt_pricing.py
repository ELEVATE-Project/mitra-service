# Per-second USD pricing for speech-to-text providers.
# Source: internal cost comparison, Aug 2026. Update here when rates change.
STT_PRICE_PER_SECOND = {
    "sarvam-stt": 0.00025,       # ~$0.015/min
    "whisper-1": 0.0001,         # $0.006/min
    "google-speech-v2": 0.000267,  # $0.016/min
    "shikshalokam-stt": 0.0,     # self-hosted
    "ai4bharat": 0.0,   
}


def compute_stt_usage_and_cost(model: str, duration_seconds: float):
    """Returns (usage_details, cost_details) for an STT generation,
    given the model name and audio duration in seconds."""
    duration_seconds = duration_seconds or 0
    usage_details = {"input": duration_seconds, "output": 0, "total": duration_seconds}

    rate = STT_PRICE_PER_SECOND.get(model)
    if rate is None:
        return usage_details, None

    input_cost = duration_seconds * rate
    cost_details = {"input": input_cost, "output": 0, "total": input_cost}
    return usage_details, cost_details


# Per-character USD pricing for text translation/transliteration providers.
# Source: internal cost comparison, Aug 2026. Update here when rates change.
TRANSLATE_PRICE_PER_CHAR = {
    "sarvam-translate": 0.000023,        # $0.23 per 10,000 chars
    "sarvam-transliterate": 0.000023,    # same rate as translate per Sarvam's pricing page
    "google-translate": 0.00002,         # $20 per 1M chars (Basic/Advanced NMT)
    "shikshalokam-translate": 0.0,        # self-hosted, unpriced
    "ai4bharat": 0.0,                     # subscription/quota-based, provider-name keyed
    # "custom_llm" intentionally excluded — routes through handle_openai_model/handle_bedrock_model,
    # which already report cost via their own generation. Adding a rate here would double-count it.
}


def compute_translate_usage_and_cost(model: str, char_count: int):
    """Returns (usage_details, cost_details) for a translation/transliteration generation,
    given the model name and input character count."""
    char_count = char_count or 0
    usage_details = {"input": char_count, "output": 0, "total": char_count}

    rate = TRANSLATE_PRICE_PER_CHAR.get(model)
    if rate is None:
        return usage_details, None

    input_cost = char_count * rate
    cost_details = {"input": input_cost, "output": 0, "total": input_cost}
    return usage_details, cost_details