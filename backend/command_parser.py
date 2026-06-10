import re
from dataclasses import dataclass
from enum import Enum


class CommandType(str, Enum):
    WAKE = "wake"
    SEND = "send"
    EXIT = "exit"
    PAUSE = "pause"
    RESUME = "resume"
    REPLAY = "replay"
    CLEAR = "clear"
    PREV = "prev"
    NEXT = "next"
    MODE_WORK = "mode_work"
    MODE_CHAT = "mode_chat"
    NONE = "none"


@dataclass
class ParseResult:
    command: CommandType
    cleaned_text: str
    confidence: float = 1.0


WAKE_WORDS = ["开始", "你好小龙虾", "小龙虾", "你好"]

SEND_WORDS = ["说完了", "发送"]
SEND_PATTERN = re.compile(r"ok\s*ok", re.IGNORECASE)

EXIT_PATTERN = re.compile(r"结束\s*结束")
EXIT_WORDS = ["退出", "退出对话"]

REPLAY_WORDS = ["重复播放", "再放一遍", "重复一遍", "再说一遍"]
PREV_WORDS = ["上一句", "上一个", "上一段"]
NEXT_WORDS = ["下一句", "下一个", "下一段"]
CLEAR_WORDS = ["清空对话", "清除对话"]
PAUSE_WORDS = ["暂停", "暂停播放", "别说了", "停一下"]
RESUME_WORDS = ["继续播放", "继续说"]
MODE_WORK_WORDS = ["工作模式", "切换工作模式"]
MODE_CHAT_WORDS = ["聊天模式", "切换聊天模式"]


def _exact_match(text: str, words: list[str]) -> bool:
    """Exact match: text equals or is very close to one of the keywords."""
    text_clean = text.strip().rstrip("。，.!！？?")
    for w in words:
        if text_clean == w:
            return True
    return False


def _contains_match(text: str, words: list[str]) -> bool:
    """Contains match: text contains one of the keywords."""
    return any(w in text for w in words)


def _is_short_text(text: str, max_len: int = 6) -> bool:
    return len(text.strip()) <= max_len


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
        return ParseResult(CommandType.NONE, "", 0.0)

    text_stripped = text.strip()

    if EXIT_PATTERN.search(text_stripped):
        return ParseResult(CommandType.EXIT, "", 1.0)
    if _exact_match(text_stripped, EXIT_WORDS):
        return ParseResult(CommandType.EXIT, "", 0.95)

    if _exact_match(text_stripped, REPLAY_WORDS):
        return ParseResult(CommandType.REPLAY, "", 0.95)
    if _is_short_text(text_stripped) and _contains_match(text_stripped, REPLAY_WORDS):
        return ParseResult(CommandType.REPLAY, "", 0.85)

    if _exact_match(text_stripped, PREV_WORDS):
        return ParseResult(CommandType.PREV, "", 0.95)
    if _is_short_text(text_stripped) and _contains_match(text_stripped, PREV_WORDS):
        return ParseResult(CommandType.PREV, "", 0.85)

    if _exact_match(text_stripped, NEXT_WORDS):
        return ParseResult(CommandType.NEXT, "", 0.95)
    if _is_short_text(text_stripped) and _contains_match(text_stripped, NEXT_WORDS):
        return ParseResult(CommandType.NEXT, "", 0.85)

    if _exact_match(text_stripped, PAUSE_WORDS):
        return ParseResult(CommandType.PAUSE, "", 0.95)
    if _is_short_text(text_stripped, 4) and _contains_match(text_stripped, ["暂停"]):
        return ParseResult(CommandType.PAUSE, "", 0.9)

    if _exact_match(text_stripped, RESUME_WORDS):
        return ParseResult(CommandType.RESUME, "", 0.95)
    if text_stripped == "继续":
        return ParseResult(CommandType.RESUME, "", 0.9)

    if _exact_match(text_stripped, CLEAR_WORDS):
        return ParseResult(CommandType.CLEAR, "", 0.95)

    if _exact_match(text_stripped, MODE_WORK_WORDS):
        return ParseResult(CommandType.MODE_WORK, "", 0.95)
    if _exact_match(text_stripped, MODE_CHAT_WORDS):
        return ParseResult(CommandType.MODE_CHAT, "", 0.95)

    if _exact_match(text_stripped, SEND_WORDS) or SEND_PATTERN.search(text_stripped):
        cleaned = _strip_send_command(text_stripped)
        return ParseResult(CommandType.SEND, cleaned, 0.95)
    if text_stripped.endswith("说完了") or text_stripped.endswith("发送"):
        cleaned = _strip_send_command(text_stripped)
        return ParseResult(CommandType.SEND, cleaned, 0.9)

    if _exact_match(text_stripped, WAKE_WORDS):
        return ParseResult(CommandType.WAKE, "", 0.95)

    return ParseResult(CommandType.NONE, text, 0.0)


def is_wake_word(text: str) -> bool:
    text_clean = text.strip().rstrip("。，.!！？?")
    for w in WAKE_WORDS:
        if text_clean == w or text_clean.endswith(w):
            return True
    return False
