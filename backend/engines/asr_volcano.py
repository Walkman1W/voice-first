import logging
import os
from .base import ASREngine

logger = logging.getLogger(__name__)

VOLCANO_APP_ID = os.environ.get("VOLCANO_APP_ID", "")
VOLCANO_TOKEN = os.environ.get("VOLCANO_TOKEN", "")


class VolcanoASREngine(ASREngine):
    """Server-side ASR engine using Volcano Engine (火山引擎) streaming API.

    TODO: Implement when Volcano Engine ASR is ready.
    Docs: https://www.volcengine.com/docs/6561/80816
    """

    name = "volcano"
    mode = "server"

    def __init__(self, app_id: str | None = None, token: str | None = None):
        self.app_id = app_id or VOLCANO_APP_ID
        self.token = token or VOLCANO_TOKEN

    async def start(self) -> None:
        if not self.app_id or not self.token:
            raise ValueError(
                "火山引擎 ASR 需要配置 VOLCANO_APP_ID 和 VOLCANO_TOKEN 环境变量"
            )
        raise NotImplementedError("火山引擎 ASR 尚未实现，请使用 edge 或 vosk 引擎")

    async def feed_audio(self, audio_chunk: bytes) -> None:
        raise NotImplementedError

    async def get_partial(self) -> str | None:
        raise NotImplementedError

    async def get_final(self) -> str | None:
        raise NotImplementedError

    async def flush_final(self) -> str | None:
        raise NotImplementedError

    async def reset(self) -> None:
        raise NotImplementedError

    async def stop(self) -> None:
        pass
