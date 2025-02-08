import os
import requests


ai4bharat_api_key = os.getenv("BHASHANI_API_KEY")


def ai4bharat_speech_text(base64, audio_format, source_language):
    try:

        if source_language == 'en':
            api_url = 'https://demo-api.models.ai4bharat.org/inference/asr/whisper'
        else:
            api_url = 'https://demo-api.models.ai4bharat.org/inference/asr/conformer'

        payload = {
            "controlConfig": {"dataTracking": True},
            "audio": [{"audioContent": base64}],
            "config": {
                "audioFormat": audio_format,
                "language": {"sourceLanguage": source_language},
                "samplingRate": 16000,
            },
            "transcriptionFormat": {"value": "transcript"}
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
            print("json response: ", audio_data)
            if isinstance(audio_data, dict) and 'output' in audio_data:
                audio_content = audio_data['output'][0].get('source', '')
                print("TRANSCRIPT: ", audio_content)
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
        return {
            'status': 500,
            'content': str(e)
        }
