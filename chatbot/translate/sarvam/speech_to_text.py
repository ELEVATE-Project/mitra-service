import base64
import os
import tempfile
import traceback
import concurrent.futures
from chatbot.translate.google.google_stt import split_audio
from sarvamai import SarvamAI
import logging


sarvam_api_key = os.getenv("SARVAM_API_KEY")
logger = logging.getLogger('django')


def transcribe_single_chunk(chunk_number, chunk, audio_format, source_language):
    try:
        client = SarvamAI(api_subscription_key=sarvam_api_key)

        with tempfile.NamedTemporaryFile(suffix=f".{audio_format}", delete=True) as tmp_file:
            tmp_file.write(chunk)
            tmp_file.flush()

            with open(tmp_file.name, "rb") as f:
                response = client.speech_to_text.transcribe(
                    file=f,
                    model="saarika:v2",
                    language_code=source_language
                )
        print("response: ", response)
        if hasattr(response, "transcript"):
            return (chunk_number, response.transcript)
        else:
            print(f"Error for chunk {chunk_number}: response is not structured as expected")
            return (chunk_number, '')

    except Exception as e:
        traceback.print_exc()
        return (chunk_number, '')


def transcribe_sarvam_multiple_chunks(voice_provider, base64_audio_file, source_language, audio_format="wav"):
    try:
        audio_bytes = base64.b64decode(base64_audio_file)
        duration = 10
        if voice_provider.other_params:
            duration = int(voice_provider.other_params.get('chunk_duration', 10))
        chunks = split_audio(audio_bytes, chunk_duration=duration)

        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = [
                executor.submit(
                    transcribe_single_chunk, chunk_number, chunk, audio_format, source_language
                )
                for chunk_number, chunk in chunks
            ]
            transcripts = [future.result() for future in concurrent.futures.as_completed(futures)]
            transcripts.sort()

        transcript = " ".join(content for _, content in transcripts)
        return {'status': 200, 'content': transcript}

    except Exception as e:
        logger.error('Error processing: %s', e, exc_info=True)
        traceback.print_exc()
        return {'status': 500, 'content': str(e)}
