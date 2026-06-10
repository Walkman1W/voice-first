"""LLM-based intent classifier using DeepSeek (OpenAI-compatible API).

Classifies user speech into: append context, trigger command, cancel, or send to agent.
Uses structured output with command_type field to avoid fragile reason-based parsing.
"""

import re
import json
import logging
from dataclasses import dataclass
from enum import Enum

import httpx

logger = logging.getLogger("crayfish.intent")


class IntentType(str, Enum):
    APPEND = "append"
    COMMAND = "command"
    CANCEL = "cancel"
    SEND = "send"


class CommandSubType(str, Enum):
    EXIT = "exit"
    PAUSE = "pause"
    RESUME = "resume"
    PREV = "prev"
    NEXT = "next"
    REPLAY = "replay"
    CLEAR = "clear"
    MODE_WORK = "mode_work"
    MODE_CHAT = "mode_chat"
    NONE = "none"


@dataclass
class IntentResult:
    intent: IntentType
    reason: str
    confidence: float = 1.0
    command_type: CommandSubType = CommandSubType.NONE


# --- Pre-filter rules ---

_VERB_PATTERN = re.compile(
    r"[吗呢吧啊呀哦么？?！!]|"
    r"什么|怎么|为什么|如何|哪|能不能|可以|请|帮|告诉|"
    r"是不是|有没有|想|要|让|给|做|说|问|查|找|看|听|"
    r"打开|关闭|设置|修改|删除|添加|创建"
)

_SENTENCE_END = re.compile(r"[。？！?!；;]$")


_PUNCTUATION = re.compile(r"[。，,.!！？?；;、：:“”‘’（）() \t\n]")


def _should_skip_llm(text: str, context: str) -> IntentResult | None:
    """Pre-filter: skip LLM call for obvious cases."""
    stripped = text.strip()
    pure_text = _PUNCTUATION.sub("", stripped)

    if len(pure_text) <= 4 and not _VERB_PATTERN.search(stripped):
        return IntentResult(intent=IntentType.APPEND, reason="short fragment", confidence=0.9)

    return None


def _local_fallback(text: str, context: str) -> IntentResult:
    """Local rule fallback when LLM fails."""
    stripped = text.strip()
    combined = (context + " " + stripped).strip() if context else stripped

    if len(combined) >= 10 and _SENTENCE_END.search(stripped):
        return IntentResult(intent=IntentType.SEND, reason="local: complete sentence", confidence=0.7)
    if len(stripped) >= 15 and _VERB_PATTERN.search(stripped):
        return IntentResult(intent=IntentType.SEND, reason="local: long with verb", confidence=0.6)

    return IntentResult(intent=IntentType.APPEND, reason="local: default append", confidence=0.5)


# --- LLM Prompt ---

CLASSIFY_SYSTEM_PROMPT = """你是一个语音助手的意图分类器。用户通过语音输入文字，你需要判断这句话的意图类别。

## 意图类别

1. **command** - 用户想执行操作命令（退出、暂停、继续播放、上一句、下一句、重复、清空对话等）
2. **send** - 用户说完了一句完整的话，想发送给AI助手处理（提问、聊天、请求帮助等）
3. **append** - 用户还没说完，这只是一个片段，应该追加到当前上下文等待更多内容
4. **cancel** - 用户想取消当前操作或输入（比如说错了、算了、不要了）

## 判断规则

- 短句且含明确操作意图词（停、退出、暂停、继续、上一个、下一个）→ command
- 完整的问句或陈述句，有明确信息需求 → send
- 不完整的句子片段、填充词、犹豫 → append
- 表达取消意图（算了、不要了、取消） → cancel
- 如果文本很短(1-3字)且不是明确命令词，倾向于 append

## 输出格式

严格输出JSON，不要有其他内容：
{"intent": "command|send|append|cancel", "command_type": "exit|pause|resume|prev|next|replay|clear|mode_work|mode_chat|none", "reason": "简短原因", "confidence": 0.0-1.0}

当 intent 不是 command 时，command_type 固定为 "none"。
注意：reason 字段只写简短中文描述，不要包含引号或特殊字符。

## 示例

输入: 当前上下文: "" 用户新输入: "暂停一下"
输出: {"intent": "command", "command_type": "pause", "reason": "明确暂停指令", "confidence": 0.95}

输入: 当前上下文: "" 用户新输入: "今天天气怎么样"
输出: {"intent": "send", "command_type": "none", "reason": "完整问句", "confidence": 0.95}

输入: 当前上下文: "我想问一下" 用户新输入: "就是那个"
输出: {"intent": "append", "command_type": "none", "reason": "不完整片段", "confidence": 0.85}

输入: 当前上下文: "帮我查一下明天的" 用户新输入: "算了不用了"
输出: {"intent": "cancel", "command_type": "none", "reason": "取消意图", "confidence": 0.9}

输入: 当前上下文: "" 用户新输入: "退出对话"
输出: {"intent": "command", "command_type": "exit", "reason": "退出指令", "confidence": 0.95}

输入: 当前上下文: "" 用户新输入: "切换到工作模式"
输出: {"intent": "command", "command_type": "mode_work", "reason": "切换交互模式", "confidence": 0.95}

输入: 当前上下文: "" 用户新输入: "用聊天模式"
输出: {"intent": "command", "command_type": "mode_chat", "reason": "切换交互模式", "confidence": 0.95}
"""

_CANCEL_WORDS = ["算了", "不要了", "取消", "不用了", "别了", "没事了"]

_QUESTION_WORDS = re.compile(
    r"什么|怎么|为什么|如何|哪里|哪个|哪些|几个|几点|多少|能不能|可不可以|是不是|有没有"
)


class RuleBasedIntentClassifier:
    """Pure rule-based intent classifier — 0ms latency, no network."""

    def __init__(self):
        self.enabled = True

    async def close(self) -> None:
        pass

    async def classify(self, text: str, context: str = "") -> IntentResult:
        stripped = text.strip()
        pure_text = _PUNCTUATION.sub("", stripped)
        combined = (context + " " + stripped).strip() if context else stripped

        if not pure_text:
            return IntentResult(intent=IntentType.APPEND, reason="empty", confidence=0.9)

        # 1. Cancel detection
        for w in _CANCEL_WORDS:
            if stripped == w or stripped.rstrip("。，.!！？?") == w:
                return IntentResult(intent=IntentType.CANCEL, reason="cancel keyword", confidence=0.95)

        # 2. Very short fragment (<=4 chars, no verb) → append
        if len(pure_text) <= 4 and not _VERB_PATTERN.search(stripped):
            return IntentResult(intent=IntentType.APPEND, reason="short fragment", confidence=0.9)

        # 3. Ends with sentence-final punctuation → send
        if _SENTENCE_END.search(stripped):
            if len(pure_text) >= 6:
                return IntentResult(intent=IntentType.SEND, reason="complete sentence", confidence=0.9)

        # 4. Contains question word + sufficient length → send
        if _QUESTION_WORDS.search(stripped) and len(pure_text) >= 6:
            return IntentResult(intent=IntentType.SEND, reason="question detected", confidence=0.85)

        # 5. Long accumulated text (context + current) → send
        combined_pure = _PUNCTUATION.sub("", combined)
        if len(combined_pure) >= 15 and _VERB_PATTERN.search(combined):
            return IntentResult(intent=IntentType.SEND, reason="long with verb", confidence=0.8)

        # 6. Default → append
        return IntentResult(intent=IntentType.APPEND, reason="default append", confidence=0.7)


# --- LLM-based classifier (DeepSeek) kept for optional use ---

CONFIDENCE_THRESHOLD = 0.7

_INTENT_RE = re.compile(r'"intent"\s*:\s*"(command|send|append|cancel)"')
_CMD_TYPE_RE = re.compile(r'"command_type"\s*:\s*"(\w+)"')
_CONFIDENCE_RE = re.compile(r'"confidence"\s*:\s*([\d.]+)')


def _try_parse_json(content: str) -> dict | None:
    """Try to parse JSON, with fallback regex extraction for malformed output."""
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        logger.debug("JSON parse attempt 1 failed: %s", e)

    # Attempt 2: extract the first { ... } block (handles trailing text)
    brace_start = content.find("{")
    brace_end = content.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        subset = content[brace_start : brace_end + 1]
        try:
            return json.loads(subset)
        except json.JSONDecodeError:
            pass

    # Attempt 3: regex extraction for core fields
    m = _INTENT_RE.search(content)
    if m:
        intent = m.group(1)
        cmd_m = _CMD_TYPE_RE.search(content)
        command_type = cmd_m.group(1) if cmd_m else "none"
        conf_m = _CONFIDENCE_RE.search(content)
        confidence = float(conf_m.group(1)) if conf_m else 0.75
        return {"intent": intent, "command_type": command_type, "reason": "parsed from partial", "confidence": confidence}

    return None


class IntentClassifier:
    def __init__(
        self,
        api_url: str = "https://api.deepseek.com/v1",
        api_key: str = "",
        model: str = "deepseek-chat",
        timeout: float = 3.0,
    ):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.enabled = bool(api_key)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=2.0, read=timeout, write=2.0, pool=2.0),
            trust_env=False,
        )
        if not self.enabled:
            logger.warning("IntentClassifier disabled: no DEEPSEEK_API_KEY configured")

    async def close(self) -> None:
        await self._client.aclose()

    async def classify(self, text: str, context: str = "") -> IntentResult:
        if not self.enabled:
            return _local_fallback(text, context)

        pre = _should_skip_llm(text, context)
        if pre is not None:
            logger.debug("Pre-filter hit: %s → %s", text[:20], pre.intent.value)
            return pre

        user_msg = f"当前上下文: \"{context}\"\n用户新输入: \"{text}\""

        try:
            request_body = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                "max_tokens": 150,
                "temperature": 0.1,
                "stream": False,
                "response_format": {"type": "json_object"},
            }

            resp = await self._client.post(
                f"{self.api_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()

            if "<think>" in content:
                content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

            if content.startswith("```"):
                content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            logger.debug("Intent raw response: %s", content[:120])

            result = _try_parse_json(content)
            if result is None:
                logger.warning("Intent JSON unparseable: %s", content[:80])
                return _local_fallback(text, context)

            intent = IntentType(result.get("intent", "append"))
            reason = result.get("reason", "")
            confidence = float(result.get("confidence", 0.8))
            command_type_str = result.get("command_type", "none")

            try:
                command_type = CommandSubType(command_type_str)
            except ValueError:
                command_type = CommandSubType.NONE

            if confidence < CONFIDENCE_THRESHOLD:
                logger.info("Low confidence (%.2f) for: %s, falling back to append", confidence, text[:30])
                return IntentResult(
                    intent=IntentType.APPEND,
                    reason=f"low confidence: {reason}",
                    confidence=confidence,
                    command_type=CommandSubType.NONE,
                )

            return IntentResult(intent=intent, reason=reason, confidence=confidence, command_type=command_type)

        except httpx.TimeoutException:
            logger.warning("Intent classification timed out for: %s", text[:30])
            return _local_fallback(text, context)
        except (httpx.HTTPStatusError, json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning("Intent classification failed: %s", e)
            return _local_fallback(text, context)
