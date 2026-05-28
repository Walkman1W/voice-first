from abc import ABC, abstractmethod


class ASREngine(ABC):
    @abstractmethod
    async def start(self) -> None:
        """Initialize the engine and load models."""

    @abstractmethod
    async def feed_audio(self, audio_chunk: bytes) -> None:
        """Feed a chunk of 16kHz 16-bit mono PCM audio."""

    @abstractmethod
    async def get_partial(self) -> str | None:
        """Return current partial recognition result, or None."""

    @abstractmethod
    async def get_final(self) -> str | None:
        """Return final recognition result if available, or None."""

    @abstractmethod
    async def flush_final(self) -> str | None:
        """Force finalize remaining audio buffer and return text, or None."""

    @abstractmethod
    async def reset(self) -> None:
        """Reset recognizer state for next utterance."""

    @abstractmethod
    async def stop(self) -> None:
        """Release resources."""


class TTSEngine(ABC):
    @abstractmethod
    async def synthesize(self, text: str) -> bytes:
        """Convert text to audio bytes (MP3 format)."""


class LLMEngine(ABC):
    @abstractmethod
    async def chat(self, message: str, history: list[dict]) -> str:
        """Send message with conversation history and return AI reply."""
