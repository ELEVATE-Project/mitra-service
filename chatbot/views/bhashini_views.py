import os
import requests
from rest_framework.decorators import api_view
from rest_framework.response import Response
from chatbot.translate.ai4Bharat.text_to_text import call_ai4bharat_translation_api


ai4bharat_api_key = os.getenv("BHASHANI_API_KEY")


@api_view(['POST'])
def ai4bharat_text_speech(request):
    try:
        body = request.data
        text = body.get('text', '')
        source_language = body.get('source_language', 'en')
        gender = body.get('gender', 'male')

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
            # Ensure audio_data is a dictionary and contains 'audio'
            if isinstance(audio_data, dict) and 'audio' in audio_data:
                audio_content = audio_data['audio'][0].get('audioContent', '')
                return Response({
                    'status': 'ok',
                    'audio': audio_content
                }, status=200)
            else:
                return Response({
                    'status': 'error',
                    'message': 'Unexpected response format from AI4Bharat API'
                }, status=500)
        else:
            return Response({
                'status': 'error',
                'message': 'Failed to fetch audio from AI4Bharat API'
            }, status=response.status_code)

    except Exception as e:
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=500)


@api_view(['POST'])
def ai4bharat_asr(request):
    try:
        body = request.data
        base64 =  body.get('base_64')
        audio_format =  body.get('audio_format', 'wav')
        source_language = body.get('source_language', 'en')

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
        print("Response: ", response)
        if response.status_code == 200:
            audio_data = response.json()
            print("json response: ", audio_data)
            if isinstance(audio_data, dict) and 'output' in audio_data:
                audio_content = audio_data['output'][0].get('source', '')
                print("TRANSCRIPT: ", audio_content)
                return Response({
                    'status': 'ok',
                    'transcript': audio_content
                }, status=200)
            else:
                return Response({
                    'status': 'error',
                    'message': 'Unexpected response format from AI4Bharat API'
                }, status=500)
        else:
            return Response({
                'status': 'error',
                'message': 'Failed to fetch audio from AI4Bharat API'
            }, status=response.status_code)

    except Exception as e:
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=500)


@api_view(['POST'])
def ai4bharat_text_translation(request):
    try:
        body = request.data
        source_language =  body.get('source_language', 'en')
        target_language =  body.get('target_language', 'en')
        message_body = body.get('message_body')

        translated_content = call_ai4bharat_translation_api(
            source_language=source_language, target_language=target_language, message_body=message_body
        )
        if translated_content is not None:
            return Response({
                'status': 'ok',
                'transcript': translated_content
            }, status=200)
        else:
            return Response({
                'status': 'error',
                'message': 'Translation failed or unexpected response from AI4Bharat API',
                'transcript': message_body
            }, status=500)

    except Exception as e:
        return Response({
            'status': 'error',
            'message': str(e),
            'transcript': request.data.get('message_body')
        }, status=500)
