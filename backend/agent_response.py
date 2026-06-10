"""Agent response model: structured text processing pipeline.

Flow: Agent text -> segmentation -> cleaning (remove markdown/emoji) -> TTS -> playback queue.
"""

import asyncio
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Awaitable

from text_segmenter import TextSegmenter


class PlaybackCommand(str, Enum):
    PAUSE = "pause"
    RESUME = "resume"
    PREV = "prev"
    NEXT = "next"
    REPLAY = "replay"
    CLEAR = "clear"


_EMOJI_RE = re.compile(
    "[\U0001f600-\U0001f64f"
    "\U0001f300-\U0001f5ff"
    "\U0001f680-\U0001f6ff"
    "\U0001f1e0-\U0001f1ff"
    "\U00002702-\U000027b0"
    "\U0001f900-\U0001f9ff"
    "\U0001fa00-\U0001fa6f"
    "\U0001fa70-\U0001faff"
    "\U00002600-\U000026ff"
    "\U0000fe0f"
    "\U000024c2-\U000024ff"
    "\U00002500-\U000025ff"
    "\U0001f000-\U0001f251]+",
    re.UNICODE,
)
_MARKDOWN_RE = re.compile(r"\*{1,3}|`{1,3}|~{2}|^#{1,6}\s*", re.MULTILINE)
_BULLET_RE = re.compile(r"^[\-\*•]\s+", re.MULTILINE)
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_EXTRA_SPACES_RE = re.compile(r"[ \t]{2,}")
_HAS_CONTENT_RE = re.compile(r"[\w一-鿿㐀-䶿]")


def clean_for_tts(text: str) -> str:
    """Remove markdown formatting, emoji, and other non-speakable content.

    Preserves numbered list markers (1. 2. 3.) so TTS reads them as sequence indicators.
    """
    text = _EMOJI_RE.sub("", text)
    text = _MARKDOWN_RE.sub("", text)
    text = _BULLET_RE.sub("", text)
    text = _LINK_RE.sub(r"\1", text)
    text = _EXTRA_SPACES_RE.sub(" ", text)
    text = text.strip()
    if not _HAS_CONTENT_RE.search(text):
        return ""
    return text


@dataclass
class AudioSegment:
    index: int
    seq: int  # sequential order number for playback (0-based)
    text: str
    cleaned_text: str = ""
    audio_b64: str = ""
    format: str = "mp3"
    is_ready: bool = False


@dataclass
class AgentResponse:
    """Holds the full AI response with segmented audio queue and playback state.

    Attributes:
        agent_name: Which agent produced this response.
        created_at: Unix timestamp when the response started.
        is_streaming: Whether the response is still being received.
        is_complete: Whether the full response text has been received.
    """

    agent_name: str = "openclaw"
    created_at: float = field(default_factory=time.time)
    is_streaming: bool = False
    is_complete: bool = False
    full_text: str = ""
    segments: list[AudioSegment] = field(default_factory=list)
    current_index: int = 0
    is_playing: bool = False
    is_paused: bool = False
    _segmenter: TextSegmenter = field(default_factory=TextSegmenter, repr=False)
    _tts_callback: Callable[[str, int], Awaitable[None]] | None = field(default=None, repr=False)
    _next_send_seq: int = field(default=0, repr=False)
    _send_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    @property
    def total_segments(self) -> int:
        return len(self.segments)

    @property
    def has_segments(self) -> bool:
        return len(self.segments) > 0

    @property
    def current_segment(self) -> AudioSegment | None:
        if 0 <= self.current_index < len(self.segments):
            return self.segments[self.current_index]
        return None

    def set_tts_callback(self, callback: Callable[[str, int], Awaitable[None]]) -> None:
        self._tts_callback = callback

    def start_streaming(self, agent_name: str = "openclaw") -> None:
        """Call when a new response stream begins."""
        self.reset()
        self.agent_name = agent_name
        self.created_at = time.time()
        self.is_streaming = True
        self.is_complete = False

    def feed_token(self, token: str) -> list[AudioSegment]:
        """Feed a streaming token. Returns new segments ready for TTS."""
        self.full_text += token
        raw_segments = self._segmenter.feed(token)
        new_segments = []
        for raw in raw_segments:
            seg = self._create_segment(raw)
            if seg:
                new_segments.append(seg)
        return new_segments

    def finish_streaming(self) -> AudioSegment | None:
        """Call when the stream is done. Flushes remaining buffer."""
        self.is_streaming = False
        self.is_complete = True
        remaining = self._segmenter.flush()
        if remaining:
            return self._create_segment(remaining)
        return None

    def _create_segment(self, raw_text: str) -> AudioSegment | None:
        cleaned = clean_for_tts(raw_text)
        if not cleaned:
            return None
        seq = len(self.segments)
        seg = AudioSegment(
            index=seq,
            seq=seq,
            text=raw_text,
            cleaned_text=cleaned,
        )
        self.segments.append(seg)
        return seg

    def add_segment(self, text: str) -> AudioSegment | None:
        """Manually add a segment (backward compat). Returns None if text is empty after cleaning."""
        return self._create_segment(text)

    def mark_segment_ready(self, index: int, audio_b64: str, fmt: str = "mp3") -> None:
        if 0 <= index < len(self.segments):
            self.segments[index].audio_b64 = audio_b64
            self.segments[index].format = fmt
            self.segments[index].is_ready = True
            self._send_event.set()

    async def wait_for_next_ready(self) -> AudioSegment | None:
        """Wait for the next segment (in seq order) to become ready. Returns None when all done."""
        while True:
            if self._next_send_seq >= len(self.segments):
                if self.is_complete:
                    return None
                self._send_event.clear()
                await self._send_event.wait()
                continue

            seg = self.segments[self._next_send_seq]
            if seg.is_ready:
                self._next_send_seq += 1
                return seg

            self._send_event.clear()
            await self._send_event.wait()

    def notify_streaming_done(self) -> None:
        """Signal that no more segments will be added. Unblocks wait_for_next_ready."""
        self._send_event.set()

    def execute_command(self, cmd: PlaybackCommand) -> dict:
        if cmd == PlaybackCommand.PAUSE:
            self.is_paused = True
            self.is_playing = False
            return {"action": "pause"}

        if cmd == PlaybackCommand.RESUME:
            self.is_paused = False
            self.is_playing = True
            return {"action": "resume"}

        if cmd == PlaybackCommand.PREV:
            self.current_index = max(0, self.current_index - 1)
            return {"action": "play_segment", "index": self.current_index}

        if cmd == PlaybackCommand.NEXT:
            self.current_index = min(len(self.segments) - 1, self.current_index + 1)
            return {"action": "play_segment", "index": self.current_index}

        if cmd == PlaybackCommand.REPLAY:
            return {"action": "play_segment", "index": self.current_index}

        if cmd == PlaybackCommand.CLEAR:
            self.is_playing = False
            self.is_paused = False
            return {"action": "clear"}

        return {"action": "none"}

    def to_status(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "created_at": self.created_at,
            "is_streaming": self.is_streaming,
            "is_complete": self.is_complete,
            "total_segments": self.total_segments,
            "current_index": self.current_index,
            "is_playing": self.is_playing,
            "is_paused": self.is_paused,
            "current_text": self.current_segment.cleaned_text if self.current_segment else "",
        }

    def reset(self) -> None:
        self.full_text = ""
        self.segments.clear()
        self.current_index = 0
        self.is_playing = False
        self.is_paused = False
        self.is_streaming = False
        self.is_complete = False
        self._next_send_seq = 0
        self._send_event.clear()
        self._segmenter.reset()
