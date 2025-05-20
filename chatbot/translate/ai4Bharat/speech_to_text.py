import base64
import os
import traceback
import requests
import json_repair
from chatbot.translate.ai4Bharat.base_translation import get_service_id
from chatbot.translate.google.google_stt import split_audio
import concurrent.futures


ai4bharat_api_key = os.getenv("BHASHANI_API_KEY")
ai4bharat_base_url = os.getenv("BHASHANI_BASE_URL")
ai4bharat_user_id = os.getenv("BHASHANI_USER_ID")
ai4bharat_authorization = os.getenv("BHASHANI_AUTHORIZATION")


def transcribe_single_chunk(chunk_number, chunk, audio_format, source_language):
    b64_chunk = base64.b64encode(chunk).decode('utf-8')
    response = ai4bharat_speech_text(
        base64=b64_chunk,
        audio_format=audio_format,
        source_language=source_language
    )
    if response['status'] == 200:
        return (chunk_number, response['content'])
    else:
        return (chunk_number, '')


def transcribe_ai4bharat_multiple_chunks(base64_audio_file, source_language, audio_format):
    try:
        audio_bytes = base64.b64decode(base64_audio_file)
        chunks = split_audio(audio_bytes, chunk_duration=10)

        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = [
                executor.submit(transcribe_single_chunk, chunk_number, chunk, audio_format, source_language)
                for chunk_number, chunk in chunks
            ]
            transcripts = [future.result() for future in concurrent.futures.as_completed(futures)]
            transcripts.sort()

        transcript = " ".join(content for _, content in transcripts)
        return {'status': 200, 'content': transcript}

    except Exception as e:
        traceback.print_exc()
        return {'status': 500, 'content': str(e)}



def ai4bharat_speech_text(base64, audio_format, source_language):
    try:

        service_id = None
        pipeline_response = get_service_id(
            task_type='asr', source_language=source_language
        )
        if pipeline_response and pipeline_response.get('success'):
            service_id = pipeline_response.get('service_id', '')
            print("service_id: ", service_id)

        payload = {
            "pipelineTasks": [
                {
                    "taskType": "asr",
                    "config": {
                        "language": {
                            "sourceLanguage": source_language,
                        },
                        "serviceId": service_id,
                        "audioFormat": audio_format,
                        "samplingRate": 16000
                    }
                }
            ],
            "inputData": {
                "audio": [
                    {
                        "audioContent": base64
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
        response = requests.post(ai4bharat_base_url, json=payload, headers=headers, timeout=30)

        if response.status_code == 200:
            print("response: ", response.text)
            audio_data = json_repair.repair_json(response.text, return_objects=True)
            if isinstance(audio_data, dict) and 'pipelineResponse' in audio_data:
                audio_content = audio_data['pipelineResponse'][0].get('output', [{}])[0].get('source', '')
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
            print("Error in response: ", response.text)
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
