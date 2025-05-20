import os
from rest_framework.decorators import api_view
from rest_framework.response import Response
from chatbot.models import CompanyBot, Voice, VoiceType
from chatbot.utils.audio_converter_utils import convert_s3_audio_to_wav_base64
from chatbot.utils.audio_provider_utils import text_speech_provider, speech_text_provider, text_translate_provider
from chatbot.utils.transliterate_utils import transliterate_text
import requests


ai4bharat_api_key = os.getenv("BHASHANI_API_KEY")


@api_view(['POST'])
def text_speech_view(request):
    try:
        body = request.data
        text = body.get('text', '')
        source_language = body.get('source_language', 'en')
        route = body.get('route')

        if not route:
            return Response({
                'status': 'error',
                'message': 'route is a required field'
            }, status=500)

        company_bot = CompanyBot.objects.filter(route=route).first()
        voice_provider = Voice.objects.filter(
            company_bot=company_bot, type=VoiceType.TextToSpeech, language=source_language
        ).first()
        print("voice_provider: ", voice_provider)
        response = text_speech_provider(
            voice_provider=voice_provider, text=text, gender=voice_provider.gender, source_language=source_language
        )

        if response.get('status') == 200:
            return Response({
                'status': 'ok',
                'audio': response.get('content')
            }, status=200)
        else:
            return Response({
                'status': 'error',
                'message': response.get('content')
            }, status=response.get('status'))

    except Exception as e:
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=500)


@api_view(['POST'])
def speech_text(request):
    try:
        body = request.data
        s3_url =  body.get('s3Url')
        audio_format =  body.get('audio_format', 'wav')
        source_language = body.get('source_language', 'en')
        route = body.get('route')

        response = requests.get(s3_url)
        response.raise_for_status()
        company_bot = CompanyBot.objects.filter(route=route).first()
        voice_provider = Voice.objects.filter(
            company_bot=company_bot, type=VoiceType.SpeechToText, language=source_language
        ).first()

        encoded_audio = convert_s3_audio_to_wav_base64(s3_url=s3_url)

        if not route:
            return Response({
                'status': 'error',
                'message': 'route is a required field'
            }, status=500)

        response = speech_text_provider(
            voice_provider=voice_provider, base64=encoded_audio, audio_format=audio_format,
            source_language=source_language
        )

        if response.get('status') == 200:
            return Response({
                'status': 'ok',
                'transcript': response.get('content')
            }, status=200)
        else:
            return Response({
                'status': 'error',
                'message': response.get('content')
            }, status=response.get('status'))

    except Exception as e:
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=500)


@api_view(['POST'])
def text_translation_view(request):
    try:
        body = request.data
        source_language =  body.get('source_language', 'en')
        target_language =  body.get('target_language', 'en')
        message_body = body.get('message_body')

        route = body.get('route')

        if not route:
            return Response({
                'status': 'error',
                'message': 'route is a required field'
            }, status=500)

        company_bot = CompanyBot.objects.filter(route=route).first()
        voice_provider = Voice.objects.filter(
            company_bot=company_bot, type=VoiceType.TextToText, language=target_language
        ).first()

        response = text_translate_provider(
            voice_provider=voice_provider, message_body=message_body, target_language=target_language,
            source_language=source_language
        )

        if response.get('status') == 200:
            return Response({
                'status': 'ok',
                'transcript': response.get('content')
            }, status=200)
        else:
            return Response({
                'status': 'error',
                'message': response.get('content')
            }, status=response.get('status'))

    except Exception as e:
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=500)


@api_view(['POST'])
def text_transliterate_view(request):
    try:
        body = request.data
        source_language =  body.get('source_language', 'en')
        target_language =  body.get('target_language', 'en')
        message_body = body.get('message_body')
        route = body.get('route')

        if not route:
            return Response({
                'status': 'error',
                'message': 'route is a required field'
            }, status=500)

        company_bot = CompanyBot.objects.filter(route=route).first()
        voice_provider = Voice.objects.filter(
            company_bot=company_bot, type=VoiceType.Transliterate, language=target_language
        ).first()

        response = transliterate_text(
            voice_provider=voice_provider, message_body=message_body, target_language=target_language,
            source_language=source_language
        )

        if response:
            return Response({
                'status': 'ok',
                'transcript': response
            }, status=200)
        else:
            return Response({
                'status': 'error',
                'message': response
            }, status=500)

    except Exception as e:
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=500)
