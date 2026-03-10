from chatbot.models.enums import VoiceProvider, VoiceType


VOICE_PROVIDER_DEFAULTS = {
    VoiceProvider.AI4Bharat: {
        VoiceType.SpeechToText: {
            "chunk_duration": 10,
            "serviceId": "bhashini/iitm/asr-dravidian--gpu--t4",
            "samplingRate": 16000,
            "preProcessors": [],
            "postProcessors": []
        },
        VoiceType.TextToText: {
            "serviceId": "bhashini/iiith/nmt-all"
        },
        VoiceType.Transliterate: {},
        VoiceType.TextToSpeech: {
            "serviceId": "Bhashini/IITM/TTS",
            "samplingRate": 22050
        }
    },

    VoiceProvider.GOOGLE: {
        VoiceType.SpeechToText: {
            "chunk_duration": 10,
            "model": "latest_long",
            "enable_automatic_punctuation": True,
            "enable_spoken_punctuation": True,
            "enable_spoken_emojis": False,
            "max_alternatives": 1,
            "profanity_filter": True,
            "enable_word_time_offsets": False,
            "boost_words": []
        },
        VoiceType.TextToText: {
            "glossary_id": None,
            "location": "global"
        }
    },

    VoiceProvider.OPENAI_WHISPER: {
        VoiceType.SpeechToText: {
            "model": "whisper-1",
            "response_format": "text",
            "temperature": 0,
            "prompt": "",
            "dictionary": [],
            "chunk_duration": 100
        }
    },

    VoiceProvider.SARVAM: {
        VoiceType.SpeechToText: {
            "chunk_duration": 10,
            "model": "saaras:v3",
            "mode": "transcribe",
        },
        VoiceType.TextToText: {
            "model": "mayura:v1",
            "mode": "modern-colloquial",
            "output_script": "fully-native",
            "numerals_format": "native"
        },

        VoiceType.Transliterate: {
            "numerals_format": "native",
            "spoken_form": True,
            "spoken_form_numerals_language": "native"
        }
    },

    VoiceProvider.CUSTOM_LLM: {
        VoiceType.SpeechToText: {},
        VoiceType.TextToText: {
            "route": "/transliterate_text"
        },
        VoiceType.Transliterate: {
            "route": "/transliterate_text"
        },
    }
}


def get_provider_defaults(provider, voice_type):
    provider_defaults = VOICE_PROVIDER_DEFAULTS.get(provider, {})
    return provider_defaults.get(voice_type, {})
