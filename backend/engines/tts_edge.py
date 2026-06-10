import asyncio
import io
import logging
import edge_tts
from .base import TTSEngine
from agent_response import clean_for_tts

logger = logging.getLogger(__name__)


class EdgeTTSEngine(TTSEngine):
    def __init__(self, voice: str = "zh-CN-XiaoxiaoNeural"):
        self.voice = voice

    async def synthesize(self, text: str) -> bytes:
        original = text
        text = clean_for_tts(text)
        if not text:
            logger.debug("TTS skip empty after clean: %r", original)
            return b""
        for attempt in range(3):
            try:
                communicate = edge_tts.Communicate(text[:500], self.voice)
                buffer = io.BytesIO()
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        buffer.write(chunk["data"])
                result = buffer.getvalue()
                if result:
                    return result
                logger.warning("TTS no audio (attempt %d): %r", attempt + 1, text[:60])
            except Exception as e:
                logger.warning("TTS error (attempt %d) for %r: %s", attempt + 1, text[:60], e)
            if attempt < 2:
                await asyncio.sleep(0.5)
        return b""
