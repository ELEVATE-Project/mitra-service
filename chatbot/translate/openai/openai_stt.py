import base64
import io
import os
from openai import OpenAI
import logging


logger = logging.getLogger('django')


def transcribe_audio(
        base64_audio: str,
        audio_format: str,
        source_language: str
) -> dict:
    """Transcribe audio from a base64 string using OpenAI's Whisper API."""
    try:
        client_api_key = os.getenv("OPENAI_API_KEY")

        client = OpenAI(api_key=client_api_key)

        audio_bytes = base64.b64decode(base64_audio)
        audio_file = io.BytesIO(audio_bytes)

        audio_file.name = f"audio.{audio_format}"

        transcription = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            response_format="text",
            language=source_language
        )
        print("transcription:", transcription)

        return {
            'status': 200,
            'content': transcription
        }
    except Exception as e:
        logger.error('Error processing file: %s', e, exc_info=True)
        return {
            'status': 500,
            'content': f"Error during API request: {e}"
        }
