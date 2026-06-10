from dataclasses import dataclass

from command_parser import CommandType, ParseResult, is_wake_word, parse_command


@dataclass
class KeywordEvent:
    action: CommandType
    text: str
    cleaned_text: str
    confidence: float = 1.0


class KeywordDispatcher:
    """Business keyword dispatch layer with confidence filtering."""

    MIN_CONFIDENCE = 0.8

    def dispatch(self, text: str) -> KeywordEvent | None:
        result: ParseResult = parse_command(text)
        if result.command == CommandType.NONE:
            return None
        if result.confidence < self.MIN_CONFIDENCE:
            return None
        return KeywordEvent(result.command, text, result.cleaned_text, result.confidence)

    def has_wake_word(self, text: str) -> bool:
        return is_wake_word(text)
