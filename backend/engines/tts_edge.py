import io
import edge_tts
from .base import TTSEngine


class EdgeTTSEngine(TTSEngine):
    def __init__(self, voice: str = "zh-CN-XiaoxiaoNeural"):
        self.voice = voice

    async def synthesize(self, text: str) -> bytes:
        communicate = edge_tts.Communicate(text[:500], self.voice)
        buffer = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buffer.write(chunk["data"])
        return buffer.getvalue()
