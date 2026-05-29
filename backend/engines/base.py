from abc import ABC, abstractmethod
from typing import AsyncIterator, Literal


class ASREngine(ABC):
    name: str = "base"
    mode: Literal["server", "client"] = "server"

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

    async def receive_result(self, text: str, is_final: bool) -> None:
        """Receive recognition result from client-side engine (used in client mode)."""


class TTSEngine(ABC):
    @abstractmethod
    async def synthesize(self, text: str) -> bytes:
        """Convert text to audio bytes (MP3 format)."""


class LLMEngine(ABC):
    @abstractmethod
    async def chat(self, message: str, history: list[dict]) -> str:
        """Send message with conversation history and return AI reply."""

    async def chat_stream(self, message: str, history: list[dict]) -> AsyncIterator[str]:
        """Stream chat response token by token. Default falls back to non-streaming."""
        result = await self.chat(message, history)
        yield result
