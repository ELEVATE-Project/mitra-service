import traceback
from typing import List
from google.cloud.speech_v2 import SpeechClient
from google.cloud.speech_v2.types import cloud_speech
import io
import wave
import base64
import concurrent.futures


def split_audio(audio_bytes, chunk_duration=50):
    """
    Splits audio into strictly 50-second chunks.
    """
    with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
        frame_rate = wf.getframerate()
        num_channels = wf.getnchannels()
        samp_width = wf.getsampwidth()
        total_frames = wf.getnframes()
        chunk_frames = chunk_duration * frame_rate  # Frames per 50s chunk

        chunks = []
        i = 0
        chunk_number = 0

        while i < total_frames:
            remaining_frames = total_frames - i
            chunk_size = min(chunk_frames, remaining_frames)

            wf.setpos(i)
            chunk_data = wf.readframes(chunk_size)

            output = io.BytesIO()
            with wave.open(output, "wb") as chunk_wf:
                chunk_wf.setnchannels(num_channels)
                chunk_wf.setsampwidth(samp_width)
                chunk_wf.setframerate(frame_rate)
                chunk_wf.writeframes(chunk_data)

            chunk_seconds = chunk_size / frame_rate
            chunk_kb = len(output.getvalue()) / 1024
            print(f"Chunk {chunk_number}: {chunk_seconds:.2f} sec, {chunk_kb:.2f} KB")

            chunks.append((chunk_number, output.getvalue()))
            i += chunk_size
            chunk_number += 1

    return chunks


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
        print(f"Error during API request for chunk {chunk_number}: {e}")
        traceback.print_exc()
        return (chunk_number, "")


def transcribe_multiple_languages_v2(
        project_id: str,
        language_codes: List[str],
        audio_file: str,
) -> dict:
    client = SpeechClient()

    try:
        print("language_codes:", language_codes)
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
        full_transcript = " ".join(transcript for _, transcript in results)

        return {'status': 200, 'content': full_transcript}

    except Exception as e:
        print(f"Error processing file: {e}")
        traceback.print_exc()
        return {'status': 500, 'content': f"Error processing file: {e}"}
