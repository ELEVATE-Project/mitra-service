import traceback
from typing import List
from google.cloud.speech_v2 import SpeechClient
from google.cloud.speech_v2.types import cloud_speech
import base64
import concurrent.futures
import logging

from chatbot.translate.base.speech_to_text import is_silent_chunk, split_audio

logger = logging.getLogger('django')


def transcribe_chunk(client, project_id, config, chunk_number, chunk):
    """Transcribes a single chunk of audio."""
    request = cloud_speech.RecognizeRequest(
        recognizer=f"projects/{project_id}/locations/global/recognizers/_",
        config=config,
        content=chunk,
    )
    try:
        response = client.recognize(request=request)
        transcript = ""
        if response and not isinstance(response, str):
            for res_result in response.results:
                if res_result and res_result.alternatives:
                    transcript += res_result.alternatives[0].transcript + " "
        return (chunk_number, transcript.strip())
    except Exception as e:
        logger.error('Error during API request for chunk %s : %s', chunk_number, e, exc_info=True)
        traceback.print_exc()
        return (chunk_number, "")


def transcribe_multiple_languages_v2(
        project_id: str,
        language_codes: List[str],
        audio_file: str,
) -> dict:
    client = SpeechClient()

    try:
        logger.info("language_codes %s", language_codes)
        config = cloud_speech.RecognitionConfig(
            auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
            language_codes=language_codes,
            model="latest_long",
        )

        audio_bytes = base64.b64decode(audio_file)
        chunks = split_audio(audio_bytes)

        transcripts = []
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_to_chunk = {
                executor.submit(transcribe_chunk, client, project_id, config, chunk_number, chunk): chunk_number
                for chunk_number, chunk in chunks
            }

            results = []
            for future in concurrent.futures.as_completed(future_to_chunk):
                chunk_number, transcript = future.result()
                results.append((chunk_number, transcript))

        results.sort()  # Ensure correct order
        logger.info("sorted results %s", results)
        full_transcript = " ".join(transcript for _, transcript in results)

        return {'status': 200, 'content': full_transcript}

    except Exception as e:
        logger.error('Error processing file: %s', e, exc_info=True)
        traceback.print_exc()
        return {'status': 500, 'content': f"Error processing file: {e}"}
