import traceback
from typing import List
from google.cloud.speech_v2 import SpeechClient
from google.cloud.speech_v2.types import cloud_speech


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

        request = cloud_speech.RecognizeRequest(
            recognizer=f"projects/{project_id}/locations/global/recognizers/_",
            config=config,
            content=audio_file,
        )

        try:
            response = client.recognize(request=request)
        except Exception as e:
            print(f"Error during API request: {e}")
            traceback.print_exc()
            return {
                'status': 500,
                'content': f"Error during API request: {e}"
            }

        transcripts = []
        if not response or isinstance(response, str):
            print("response: ", response)
        for res_result in response.results:
            print("res_result: ", res_result)
            if res_result and res_result.alternatives:
                transcript = res_result.alternatives[0].transcript
            else:
                transcript = ''
            transcripts.append(transcript)
            print(f"Transcript: {transcript}")

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
