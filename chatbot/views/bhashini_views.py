import os
from rest_framework.decorators import api_view
from rest_framework.response import Response
from chatbot.models import CompanyBot, Voice, VoiceType
from chatbot.utils.audio_provider_utils import text_speech_provider, speech_text_provider, text_translate_provider

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
        base64 =  body.get('base_64')
        audio_format =  body.get('audio_format', 'wav')
        source_language = body.get('source_language', 'en')
        route = body.get('route')

        if not route:
            return Response({
                'status': 'error',
                'message': 'route is a required field'
            }, status=500)

        company_bot = CompanyBot.objects.filter(route=route).first()
        voice_provider = Voice.objects.filter(company_bot=company_bot, type=VoiceType.SpeechToText).first()

        response = speech_text_provider(
            voice_provider=voice_provider, base64=base64, audio_format=audio_format,
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
        voice_provider = Voice.objects.filter(company_bot=company_bot, type=VoiceType.TextToText).first()

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
