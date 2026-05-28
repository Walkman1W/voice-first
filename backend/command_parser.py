import re
from dataclasses import dataclass
from enum import Enum


class CommandType(str, Enum):
    WAKE = "wake"
    SEND = "send"
    EXIT = "exit"
    REPLAY = "replay"
    CLEAR = "clear"
    NONE = "none"


@dataclass
class ParseResult:
    command: CommandType
    cleaned_text: str


WAKE_WORDS = ["开始", "你好小龙虾", "小龙虾", "你好"]
SEND_WORDS = ["说完了", "发送"]
SEND_PATTERN = re.compile(r"ok\s*ok", re.IGNORECASE)
EXIT_PATTERN = re.compile(r"结束\s*结束")
EXIT_WORDS = ["退出"]
REPLAY_WORDS = ["重复播放", "再放一遍", "重复一遍"]
CLEAR_WORDS = ["清空对话"]


def _match_any(text: str, words: list[str]) -> bool:
    return any(w in text for w in words)


def _strip_send_command(text: str) -> str:
    result = text
    for w in SEND_WORDS:
        idx = result.rfind(w)
        if idx >= 0:
            result = result[:idx] + result[idx + len(w):]
    result = re.sub(r"ok\s*ok\s*$", "", result, flags=re.IGNORECASE)
    return result.strip()


def parse_command(text: str) -> ParseResult:
    if not text:
        return ParseResult(CommandType.NONE, "")

    if EXIT_PATTERN.search(text) or _match_any(text, EXIT_WORDS):
        return ParseResult(CommandType.EXIT, "")

    if _match_any(text, REPLAY_WORDS):
        return ParseResult(CommandType.REPLAY, "")

    if _match_any(text, CLEAR_WORDS):
        return ParseResult(CommandType.CLEAR, "")

    if _match_any(text, SEND_WORDS) or SEND_PATTERN.search(text):
        cleaned = _strip_send_command(text)
        return ParseResult(CommandType.SEND, cleaned)

    if _match_any(text, WAKE_WORDS):
        return ParseResult(CommandType.WAKE, "")

    return ParseResult(CommandType.NONE, text)


def is_wake_word(text: str) -> bool:
    return _match_any(text, WAKE_WORDS)
