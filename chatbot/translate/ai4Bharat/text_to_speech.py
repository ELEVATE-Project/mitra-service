import os
import traceback
import requests
from rest_framework.response import Response


ai4bharat_api_key = os.getenv("BHASHANI_API_KEY")


def ai4bharat_text_speech(text, gender, source_language):
    try:

        api_url = 'https://demo-api.models.ai4bharat.org/inference/tts'

        payload = {
            "controlConfig": {"dataTracking": True},
            "input": [{"source": text}],
            "config": {
                "gender": gender,
                "language": {"sourceLanguage": source_language},
            },
        }

        headers = {
            'accept': '*/*',
            'content-type': 'application/json',
            'origin': 'https://models.ai4bharat.org',
            'referer': 'https://models.ai4bharat.org/',
            'ulcaApiKey': ai4bharat_api_key
        }

        response = requests.post(api_url, json=payload, headers=headers, timeout=10)
        if response.status_code == 200:
            audio_data = response.json()
            if isinstance(audio_data, dict) and 'audio' in audio_data:
                audio_content = audio_data['audio'][0].get('audioContent', '')
                return {
                    'status': 200,
                    'content': audio_content
                }
            else:
                return {
                    'status': 500,
                    'content': 'Unexpected response format from AI4Bharat API'
                }
        else:
            return {
                'status': response.status_code,
                'content': 'Failed to fetch audio from AI4Bharat API'
            }

    except Exception as e:
        traceback.print_exc()
        return {
            'status': 500,
            'content': str(e)
        }
