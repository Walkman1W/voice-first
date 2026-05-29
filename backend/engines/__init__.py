import os
import logging

from .base import ASREngine, TTSEngine, LLMEngine
from .asr_vosk import VoskASREngine
from .asr_edge import EdgeASREngine
from .asr_volcano import VolcanoASREngine
from .tts_edge import EdgeTTSEngine
from .llm_openclaw import OpenClawLLMEngine

logger = logging.getLogger(__name__)

__all__ = [
    "ASREngine", "TTSEngine", "LLMEngine",
    "VoskASREngine", "EdgeASREngine", "VolcanoASREngine",
    "EdgeTTSEngine", "OpenClawLLMEngine",
    "create_asr_engine",
]

ASR_ENGINES = {
    "edge": EdgeASREngine,
    "vosk": VoskASREngine,
    "volcano": VolcanoASREngine,
}


def create_asr_engine(engine_name: str | None = None, **kwargs) -> ASREngine:
    name = (engine_name or os.environ.get("ASR_ENGINE", "edge")).lower()
    if name not in ASR_ENGINES:
        raise ValueError(
            f"Unknown ASR engine: {name}. Available: {', '.join(ASR_ENGINES.keys())}"
        )
    logger.info("Creating ASR engine: %s", name)
    cls = ASR_ENGINES[name]
    if name == "vosk":
        return cls(model_path=kwargs.get("model_path"))
    if name == "volcano":
        return cls(app_id=kwargs.get("app_id"), token=kwargs.get("token"))
    return cls()
