import os
import traceback
import requests
from chatbot.translate.ai4Bharat.base_translation import get_service_id

ai4bharat_api_key = os.getenv("BHASHANI_API_KEY")
ai4bharat_base_url = os.getenv("BHASHANI_BASE_URL")
ai4bharat_user_id = os.getenv("BHASHANI_USER_ID")
ai4bharat_authorization = os.getenv("BHASHANI_AUTHORIZATION")


def ai4bharat_text_speech(text, gender, source_language):
    try:

        api_url = ai4bharat_base_url
        print("gender: ", gender)
        print("source_language: ", source_language)
        print("original text: ", text)

        service_id = None
        pipeline_response = get_service_id(
            task_type='tts', source_language=source_language
        )
        if pipeline_response and pipeline_response.get('success'):
            service_id = pipeline_response.get('service_id', '')
            print("service_id: ", service_id)

        payload = {
            "pipelineTasks": [
                {
                    "taskType": "tts",
                    "config": {
                        "language": {
                            "sourceLanguage": source_language,
                        },
                        "serviceId": service_id,
                        "gender": gender.lower(),
                        "samplingRate": 8000
                    }
                }
            ],
            "inputData": {
                "input": [
                    {
                        "source": text
                    }
                ]
            }
        }

        headers = {
            'accept': '*/*',
            'content-type': 'application/json',
            'Authorization': ai4bharat_authorization,
            'userID': ai4bharat_user_id,
            'ulcaApiKey': ai4bharat_api_key
        }

        response = requests.post(api_url, json=payload, headers=headers, timeout=10)
        if response.status_code == 200:
            audio_data = response.json()
            if isinstance(audio_data, dict) and 'pipelineResponse' in audio_data:
                audio_content = audio_data['pipelineResponse'][0].get('audio', [{}])[0].get('audioContent', '')
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
