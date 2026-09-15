import os
import logging
import requests

logger = logging.getLogger('django')

ai4bharat_api_key = os.getenv("BHASHANI_API_KEY")
ai4bharat_base_url = os.getenv("BHASHANI_BASE_URL")
ai4bharat_user_id = os.getenv("BHASHANI_USER_ID")
ai4bharat_authorization = os.getenv("BHASHANI_AUTHORIZATION")


def ai4bharat_text_speech(voice_provider, text, gender, source_language):
    try:

        api_url = ai4bharat_base_url

        other_params = voice_provider.other_params if voice_provider.other_params else {}

        payload = {
            "pipelineTasks": [
                {
                    "taskType": "tts",
                    "config": {
                        "language": {
                            "sourceLanguage": source_language,
                        },
                        "gender": gender.lower(),
                        "serviceId": other_params.get('serviceId', 'Bhashini/IITM/TTS'),
                        "samplingRate": other_params.get('samplingRate', 22050),
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
        }
        request_timeout = other_params.get("request_timeout", 10)

        try:
            request_timeout = float(request_timeout)
        except Exception:
            request_timeout = 10

        response = requests.post(api_url, json=payload, headers=headers, timeout=request_timeout)
        cid = response.headers.get('x-correlation-id', 'N/A')
        if response.status_code == 200:
            audio_data = response.json()
            if isinstance(audio_data, dict) and 'pipelineResponse' in audio_data:
                audio_content = audio_data['pipelineResponse'][0].get('audio', [{}])[0].get('audioContent', '')
                logger.info(f"[AI4Bharat][TTS] status={response.status_code} x-correlation-id={cid}")
                return {
                    'status': 200,
                    'content': audio_content
                }
            else:
                logger.error(f"[AI4Bharat][TTS] status={response.status_code} x-correlation-id={cid} error=unexpected_format")
                return {
                    'status': 500,
                    'content': 'Unexpected response format from AI4Bharat API'
                }
        else:
            logger.error(f"[AI4Bharat][TTS] status={response.status_code} x-correlation-id={cid} error={response.text}")
            return {
                'status': response.status_code,
                'content': 'Failed to fetch audio from AI4Bharat API'
            }

    except Exception as e:
        logger.error(f"[AI4Bharat][TTS] x-correlation-id=N/A error={e}", exc_info=True)
        return {
            'status': 500,
            'content': str(e)
        }
