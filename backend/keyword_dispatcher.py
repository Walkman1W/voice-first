from dataclasses import dataclass

from command_parser import CommandType, ParseResult, is_wake_word, parse_command


@dataclass
class KeywordEvent:
    action: CommandType
    text: str
    cleaned_text: str


class KeywordDispatcher:
    """Business keyword dispatch layer kept separate from ASR text decoding."""

    def dispatch(self, text: str) -> KeywordEvent | None:
        result: ParseResult = parse_command(text)
        if result.command == CommandType.NONE:
            return None
        return KeywordEvent(result.command, text, result.cleaned_text)

    def has_wake_word(self, text: str) -> bool:
        return is_wake_word(text)
