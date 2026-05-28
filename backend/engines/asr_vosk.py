import json
import asyncio
import logging
from pathlib import Path
from .base import ASREngine

logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).parent.parent / "models" / "vosk-model-small-cn-0.22"


class VoskASREngine(ASREngine):
    def __init__(self, model_path: str | None = None, sample_rate: int = 16000):
        self.model_path = model_path or str(MODEL_PATH)
        self.sample_rate = sample_rate
        self._model = None
        self._recognizer = None
        self._partial = ""
        self._final: str | None = None

    async def start(self) -> None:
        import vosk
        vosk.SetLogLevel(-1)
        if not Path(self.model_path).exists():
            raise FileNotFoundError(
                f"Vosk model not found at {self.model_path}. "
                f"Download from https://alphacephei.com/vosk/models and extract to that path."
            )
        self._model = vosk.Model(self.model_path)
        self._recognizer = vosk.KaldiRecognizer(self._model, self.sample_rate)
        logger.info("Vosk ASR engine initialized with model: %s", self.model_path)

    async def feed_audio(self, audio_chunk: bytes) -> None:
        if not self._recognizer:
            return
        loop = asyncio.get_event_loop()
        accepted = await loop.run_in_executor(
            None, self._recognizer.AcceptWaveform, audio_chunk
        )
        if accepted:
            result = json.loads(self._recognizer.Result())
            text = result.get("text", "").strip()
            if text:
                self._final = text
        else:
            partial = json.loads(self._recognizer.PartialResult())
            self._partial = partial.get("partial", "")

    async def get_partial(self) -> str | None:
        return self._partial if self._partial else None

    async def get_final(self) -> str | None:
        result = self._final
        self._final = None
        return result

    async def flush_final(self) -> str | None:
        if not self._recognizer:
            return None
        result = json.loads(self._recognizer.FinalResult())
        text = result.get("text", "").strip()
        return text if text else None

    async def reset(self) -> None:
        if self._recognizer and self._model:
            import vosk
            self._recognizer = vosk.KaldiRecognizer(self._model, self.sample_rate)
        self._partial = ""
        self._final = None

    async def stop(self) -> None:
        self._recognizer = None
        self._model = None
