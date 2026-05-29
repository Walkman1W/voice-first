import logging
from .base import ASREngine

logger = logging.getLogger(__name__)


class EdgeASREngine(ASREngine):
    """Client-side ASR engine using browser Web Speech API.

    The actual recognition happens in the browser. This engine receives
    partial/final results forwarded from the frontend via WebSocket.
    """

    name = "edge"
    mode = "client"

    def __init__(self):
        self._partial: str | None = None
        self._final: str | None = None

    async def start(self) -> None:
        logger.info("Edge ASR engine initialized (client-side, browser Web Speech API)")

    async def feed_audio(self, audio_chunk: bytes) -> None:
        pass

    async def get_partial(self) -> str | None:
        return self._partial

    async def get_final(self) -> str | None:
        result = self._final
        self._final = None
        return result

    async def flush_final(self) -> str | None:
        result = self._final or self._partial
        self._final = None
        self._partial = None
        return result if result else None

    async def reset(self) -> None:
        self._partial = None
        self._final = None

    async def stop(self) -> None:
        self._partial = None
        self._final = None

    async def receive_result(self, text: str, is_final: bool) -> None:
        if is_final:
            self._final = text
            self._partial = None
        else:
            self._partial = text
