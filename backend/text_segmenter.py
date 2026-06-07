import re

SENTENCE_ENDINGS = re.compile(r'([。！？；\n]|\.{3}|…)')
CLAUSE_ENDINGS = re.compile(r'([，,、：:）)」』】])')

MIN_SEGMENT_LEN = 8
MAX_SEGMENT_LEN = 80


class TextSegmenter:
    """Splits streaming text into sentence-level segments for TTS."""

    def __init__(self):
        self._buffer = ""

    def feed(self, text: str) -> list[str]:
        """Feed new text chunk, return completed segments."""
        self._buffer += text
        segments = []

        while True:
            m = SENTENCE_ENDINGS.search(self._buffer)
            if m:
                end = m.end()
                seg = self._buffer[:end].strip()
                self._buffer = self._buffer[end:]
                if seg:
                    segments.append(seg)
                continue

            if len(self._buffer) >= MAX_SEGMENT_LEN:
                m2 = CLAUSE_ENDINGS.search(self._buffer)
                if m2 and m2.end() >= MIN_SEGMENT_LEN:
                    end = m2.end()
                    seg = self._buffer[:end].strip()
                    self._buffer = self._buffer[end:]
                    if seg:
                        segments.append(seg)
                    continue
                seg = self._buffer[:MAX_SEGMENT_LEN].strip()
                self._buffer = self._buffer[MAX_SEGMENT_LEN:]
                if seg:
                    segments.append(seg)
                continue

            break

        return segments

    def flush(self) -> str | None:
        """Flush remaining buffer as final segment."""
        seg = self._buffer.strip()
        self._buffer = ""
        return seg if seg else None

    def reset(self) -> None:
        self._buffer = ""
