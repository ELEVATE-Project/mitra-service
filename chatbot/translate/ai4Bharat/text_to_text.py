import os
import traceback
import requests
from chatbot.translate.ai4Bharat.base_translation import get_service_id
import logging


ai4bharat_api_key = os.getenv("BHASHANI_API_KEY")
ai4bharat_base_url = os.getenv("BHASHANI_BASE_URL")
ai4bharat_user_id = os.getenv("BHASHANI_USER_ID")
ai4bharat_authorization = os.getenv("BHASHANI_AUTHORIZATION")
logger = logging.getLogger('django')


def call_ai4bharat_translation_api(source_language, target_language, message_body):
    api_url = ai4bharat_base_url
    service_id = None
    pipeline_response = get_service_id(
        task_type='translation', source_language=source_language, target_language=target_language
    )
    if pipeline_response and pipeline_response.get('success'):
        service_id = pipeline_response.get('service_id', '')
        print("service_id: ", service_id)

    payload = {
        "pipelineTasks": [
            {
                "taskType": "translation",
                "config": {
                    "language": {
                        "sourceLanguage": source_language,
                        "targetLanguage": target_language,
                    },
                    "serviceId": service_id,
                    "isSentence": True,
                    "numSuggestions": 7
                }
            }
        ],
        "inputData": {
            "input": [
                {
                    "source": message_body
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

    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=10)
        print("Response: ", response)
        print("Res text: ", response.json())
        logger.info(f"Response {response}")
        logger.info(f"Response text {response.json()}")

        if response.status_code == 200:
            translated_data = response.json()
            if isinstance(translated_data, dict) and 'pipelineResponse' in translated_data:
                translated_message = translated_data['pipelineResponse'][0].get('output', [{}])[0].get('target', '')

                print("translated_message: ", translated_message)
                return {
                    'status': 200,
                    'content': translated_message
                }
        return {
            'status': 200,
            'content': message_body
        }
    except Exception as e:
        logger.error('Error processing: %s', e, exc_info=True)
        print(f"Error during translation API call: {str(e)}")
        traceback.print_exc()
        return {
            'status': 500,
            'content': f"Error during translation API call: {str(e)}"
        }
