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


# Purpose: Transliterates a word or sentence from source_language script to target_language script
#          using the AI4Bharat Bhashani pipeline API. Only the first of up to 7 requested
#          suggestions is returned.
# Inputs:  source_language — ISO language code (e.g. 'en'); target_language — target script code;
#          message_body — text to transliterate; is_sentence — False for single words (default)
# Output:  {"status": 200, "content": <transliterated string>} on success;
#          {"status": 200, "content": original message_body} on non-200 response or unexpected
#          payload shape (silent fallback, not an error signal);
#          {"status": 500, "content": original message_body} only if an exception is raised
# Side effects: External HTTP call to AI4Bharat Bhashani API
def call_ai4bharat_transliterate_api(source_language, target_language, message_body, is_sentence=False, timeout=30):
    logger.info(f"Trying to transliterate {message_body}.")
    api_url = ai4bharat_base_url
    service_id = None
    pipeline_response = get_service_id(
        task_type='transliteration', source_language=source_language, target_language=target_language
    )
    if pipeline_response and pipeline_response.get('success'):
        service_id = pipeline_response.get('service_id', '')
        print("service_id: ", service_id)
    # service_id may remain None if pipeline lookup fails — API call proceeds anyway

    payload = {
        "pipelineTasks": [
            {
                "taskType": "transliteration",
                "config": {
                    "language": {
                        "sourceLanguage": source_language,
                        "targetLanguage": target_language,
                    },
                    "serviceId": service_id,
                    "isSentence": is_sentence,
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
        response = requests.post(api_url, json=payload, headers=headers, timeout=timeout)
        print("Response: ", response)
        print("Res text: ", response.json())
        logger.info(f"Response from AI4Bharat Transliteration: {response}")
        logger.info(f"JSON Response from AI4Bharat Transliteration: {response.json()}")
        if response.status_code == 200:
            transliteration_message_data = response.json()
            if isinstance(transliteration_message_data, dict) and 'pipelineResponse' in transliteration_message_data:
                transliteration_message = transliteration_message_data['pipelineResponse'][0].get('output', [{}])[0].get('target', '')

                print("transliteration: ", transliteration_message)
                return {
                    'status': 200,
                    'content': transliteration_message
                }
        # API returned non-200 or unexpected shape — fall back to original text silently
        return {
            'status': 200,
            'content': message_body
        }
    except Exception as e:
        print(f"Error during transliteration API call: {str(e)}")
        logger.error(f"Error during transliteration API call: {str(e)}")
        traceback.print_exc()
        return {
            'status': 500,
            'content': message_body
        }
