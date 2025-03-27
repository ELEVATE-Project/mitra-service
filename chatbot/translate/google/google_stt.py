import traceback
from typing import List
from google.cloud.speech_v2 import SpeechClient
from google.cloud.speech_v2.types import cloud_speech
import io
import wave
import base64


def split_audio(audio_bytes, chunk_duration=50):
    """
    Splits audio into 50-second chunks.
    """
    with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
        frame_rate = wf.getframerate()
        num_channels = wf.getnchannels()
        samp_width = wf.getsampwidth()
        total_frames = wf.getnframes()
        chunk_frames = chunk_duration * frame_rate

        chunks = []
        for i in range(0, total_frames, chunk_frames):
            wf.setpos(i)
            chunk_data = wf.readframes(min(chunk_frames, total_frames - i))
            output = io.BytesIO()
            with wave.open(output, "wb") as chunk_wf:
                chunk_wf.setnchannels(num_channels)
                chunk_wf.setsampwidth(samp_width)
                chunk_wf.setframerate(frame_rate)
                chunk_wf.writeframes(chunk_data)
            chunks.append(output.getvalue())
    return chunks


def transcribe_multiple_languages_v2(
    project_id: str,
    language_codes: List[str],
    audio_file: str,
) -> dict:
    client = SpeechClient()

    try:
        print("language_codes: ", language_codes)
        config = cloud_speech.RecognitionConfig(
            auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
            language_codes=language_codes,
            model="latest_long",
        )

        audio_bytes = base64.b64decode(audio_file)
        chunks = split_audio(audio_bytes)

        transcripts = []

        for chunk in chunks:
            request = cloud_speech.RecognizeRequest(
                recognizer=f"projects/{project_id}/locations/global/recognizers/_",
                config=config,
                content=chunk,
            )
            try:
                response = client.recognize(request=request)
                if response and not isinstance(response, str):
                    for res_result in response.results:
                        if res_result and res_result.alternatives:
                            transcripts.append(res_result.alternatives[0].transcript)
            except Exception as e:
                print(f"Error during API request: {e}")
                traceback.print_exc()
                return {
                    'status': 500,
                    'content': f"Error during API request: {e}"
                }
        print("transcripts: ", transcripts)
        full_transcript = " ".join(transcripts)
        return {
            'status': 200,
            'content': full_transcript
        }

    except Exception as e:
        print(f"Error processing file: {e}")
        traceback.print_exc()
        return {
            'status': 500,
            'content': f"Error processing file: {e}"
        }
