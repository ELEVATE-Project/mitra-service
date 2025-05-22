import io
import traceback
from pydub import AudioSegment


def is_silent_chunk(audio_bytes: bytes, format="wav", silence_thresh_dbfs=-40):
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format=format)
        return audio.dBFS < silence_thresh_dbfs
    except Exception:
        traceback.print_exc()
        return False