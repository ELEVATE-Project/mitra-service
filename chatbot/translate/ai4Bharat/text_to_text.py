import os
import requests

ai4bharat_api_key = os.getenv("BHASHANI_API_KEY")


def call_ai4bharat_translation_api(source_language, target_language, message_body):
    api_url = 'https://demo-api.models.ai4bharat.org/inference/translation/v2'
    print("\n\nTranslation message body req data: ", message_body)
    payload = {
        "controlConfig": {"dataTracking": True},
        "input": [{"source": message_body}],
        "config": {
            "language": {
                "sourceLanguage": source_language,
                "targetLanguage": target_language,
            },
        },
    }

    headers = {
        'accept': '*/*',
        'content-type': 'application/json',
        'origin': 'https://models.ai4bharat.org',
        'referer': 'https://models.ai4bharat.org/',
        'ulcaApiKey': ai4bharat_api_key
    }

    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=10)
        if response.status_code == 200:
            translated_data = response.json()
            if isinstance(translated_data, dict) and 'output' in translated_data:
                translated_message = translated_data['output'][0].get('target', '')
                print("translated_message: ", translated_message)
                return translated_message
        return message_body
    except Exception as e:
        print(f"Error during translation API call: {str(e)}")
        return message_body
