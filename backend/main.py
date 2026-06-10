import base64
import json
import logging
import os
import asyncio
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from state_machine import StateMachine, State
from command_parser import CommandType
from keyword_dispatcher import KeywordDispatcher
from agent_response import AgentResponse, PlaybackCommand
from intent_classifier import IntentClassifier, RuleBasedIntentClassifier, IntentType, CommandSubType
from engines import EdgeTTSEngine, OpenClawLLMEngine, create_asr_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("crayfish")

app = FastAPI(title="Crayfish Voice Assistant Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
ROOT_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT_DIR / "dist"

GATEWAY_URL = os.environ.get("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
GATEWAY_TOKEN = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "89511f3f33f4255def0cfc032175a56bcb2c1c1e09dad63e")
TTS_VOICE = os.environ.get("TTS_VOICE", "zh-CN-XiaoxiaoNeural")
VOSK_MODEL = os.environ.get("VOSK_MODEL_PATH", None)
ASR_ENGINE_NAME = os.environ.get("ASR_ENGINE", "edge")

VOLCANO_ASR_APP_KEY = os.environ.get("VOLCANO_ASR_APP_KEY", "")
VOLCANO_ASR_ACCESS_KEY = os.environ.get("VOLCANO_ASR_ACCESS_KEY", "")
VOLCANO_ASR_WS_URL = os.environ.get("VOLCANO_ASR_WS_URL", "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel")
VOLCANO_ASR_RESOURCE_ID = os.environ.get("VOLCANO_ASR_RESOURCE_ID", "volc.bigasr.sauc.duration")

DEEPSEEK_API_URL = os.environ.get("DEEPSEEK_API_URL", "https://api.deepseek.com/v1")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

INTERACTION_MODE = os.environ.get("INTERACTION_MODE", "work")
SILENCE_TIMEOUT_S = float(os.environ.get("SILENCE_TIMEOUT_S", "5"))
INTENT_ENGINE = os.environ.get("INTENT_ENGINE", "rule")  # "rule" or "deepseek"

_COMMAND_SUBTYPE_MAP = {
    CommandSubType.EXIT: CommandType.EXIT,
    CommandSubType.PAUSE: CommandType.PAUSE,
    CommandSubType.RESUME: CommandType.RESUME,
    CommandSubType.PREV: CommandType.PREV,
    CommandSubType.NEXT: CommandType.NEXT,
    CommandSubType.REPLAY: CommandType.REPLAY,
    CommandSubType.CLEAR: CommandType.CLEAR,
    CommandSubType.MODE_WORK: CommandType.MODE_WORK,
    CommandSubType.MODE_CHAT: CommandType.MODE_CHAT,
    CommandSubType.NONE: CommandType.NONE,
}


class Session:
    """Per-WebSocket connection session managing engines and state."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.sm = StateMachine()
        self.asr = create_asr_engine(ASR_ENGINE_NAME, model_path=VOSK_MODEL)
        self.tts = EdgeTTSEngine(voice=TTS_VOICE)
        self.llm = OpenClawLLMEngine(base_url=GATEWAY_URL, token=GATEWAY_TOKEN)
        self.dispatcher = KeywordDispatcher()
        if INTENT_ENGINE == "deepseek":
            self.intent_classifier = IntentClassifier(
                api_url=DEEPSEEK_API_URL,
                api_key=DEEPSEEK_API_KEY,
                model=DEEPSEEK_MODEL,
            )
        else:
            self.intent_classifier = RuleBasedIntentClassifier()
        self.chat_history: list[dict] = []
        self.accumulated_text = ""
        self.last_tts_text = ""
        self.voice_active = False
        self.pending_send_text = ""
        self.interaction_mode = INTERACTION_MODE
        self._processing_tasks: set[asyncio.Task] = set()
        self._pending_send_task: asyncio.Task | None = None
        self._conversation_lock = asyncio.Lock()
        self.tts_segments: list[str] = []
        self.tts_segment_index: int = 0
        self.agent_response = AgentResponse()
        self.sm.on_state_change(self._on_state_change)
        self._asr_start_time: float = 0
        self._voice_start_time: float = 0

    async def _on_state_change(self, state: State, description: str) -> None:
        await self._send({"type": "state_change", "state": state.value, "text": description})

    async def _send(self, msg: dict) -> None:
        try:
            await self.ws.send_json(msg)
        except Exception as e:
            logger.debug("Send failed: %s", e)

    async def initialize(self) -> None:
        try:
            await self.asr.start()
            logger.info("Session initialized with ASR engine: %s (mode: %s)", self.asr.name, self.asr.mode)
        except FileNotFoundError as e:
            logger.warning("ASR not available: %s", e)
            await self._send({"type": "error", "message": f"ASR unavailable: {e}"})
        except ImportError:
            logger.warning("vosk package not installed, ASR disabled")
            await self._send({"type": "error", "message": "vosk not installed, ASR disabled"})
        except NotImplementedError as e:
            logger.warning("ASR engine not implemented: %s", e)
            await self._send({"type": "error", "message": str(e)})
        await self._send({
            "type": "asr_config",
            "mode": self.asr.mode,
            "engine": self.asr.name,
        })
        await self.sm.transition(State.WAKE_LISTENING, "等待唤醒词")

    async def cleanup(self) -> None:
        if self._pending_send_task and not self._pending_send_task.done():
            self._pending_send_task.cancel()
        for task in self._processing_tasks:
            if not task.done():
                task.cancel()
        await self.asr.stop()
        await self.llm.close()
        await self.intent_classifier.close()

    async def handle_message(self, data: dict) -> None:
        msg_type = data.get("type", "")

        if msg_type == "command":
            await self._handle_command(data)
        elif msg_type == "audio_data":
            await self._handle_audio(data)
        elif msg_type == "voice_start":
            await self._handle_voice_start()
        elif msg_type == "voice_end":
            await self._handle_voice_end()
        elif msg_type == "text_input":
            await self._handle_text_input(data.get("text", ""))
        elif msg_type == "tts_playback_done":
            await self._handle_tts_playback_done()
        elif msg_type == "asr_result":
            await self._handle_asr_result(data)
        elif msg_type == "playback_command":
            await self._handle_playback_command(data)
        else:
            await self._send({"type": "error", "message": f"Unknown message type: {msg_type}"})

    async def _handle_command(self, data: dict) -> None:
        action = data.get("action", "")
        if action == "start_wake":
            await self.sm.transition(State.WAKE_LISTENING, "等待唤醒词")
            await self.asr.reset()
            self.accumulated_text = ""
            await self._send({"type": "command_result", "action": action, "success": True})
        elif action == "start_conversation":
            await self.sm.transition(State.LISTENING, "聆听中")
            await self.asr.reset()
            self.accumulated_text = ""
            await self._send({"type": "command_result", "action": action, "success": True})
        elif action == "stop":
            if self._pending_send_task and not self._pending_send_task.done():
                self._pending_send_task.cancel()
            for task in self._processing_tasks:
                if not task.done():
                    task.cancel()
            self._processing_tasks.clear()
            await self.sm.force_state(State.IDLE, "已停止")
            await self.asr.reset()
            self.accumulated_text = ""
            self.pending_send_text = ""
            await self._send({"type": "command_result", "action": action, "success": True})
        elif action == "clear":
            async with self._conversation_lock:
                self.chat_history.clear()
            await self._send({"type": "command_result", "action": action, "success": True})
        else:
            await self._send({"type": "error", "message": f"Unknown command: {action}"})

    async def _handle_voice_start(self) -> None:
        self.voice_active = True
        self._voice_start_time = time.time()
        await self._send({"type": "vad_event", "action": "voice_start", "text": "检测到人声"})
        if self._pending_send_task and not self._pending_send_task.done():
            self._pending_send_task.cancel()
            await self._send({"type": "track_update", "track": "input", "active": True, "text": "继续说话，取消待发送倒计时"})
        if self.pending_send_text:
            self.accumulated_text = (self.pending_send_text + " " + self.accumulated_text).strip()
            self.pending_send_text = ""
            await self._send({"type": "track_update", "track": "input", "active": True, "text": "继续说话，已保留待发送内容"})
        state = self.sm.state
        if state == State.WAKE_LISTENING:
            pass
        elif state == State.LISTENING:
            await self.sm.transition(State.RECOGNIZING, "识别中")
            await self.asr.reset()

    async def _handle_audio(self, data: dict) -> None:
        state = self.sm.state
        if state not in (State.WAKE_LISTENING, State.LISTENING, State.RECOGNIZING, State.PLAYING):
            return

        audio_b64 = data.get("data", "")
        if not audio_b64:
            return
        audio_bytes = base64.b64decode(audio_b64)
        await self.asr.feed_audio(audio_bytes)

        final = await self.asr.get_final()
        if final:
            await self._process_recognized_text(final, is_final=True)
        else:
            partial = await self.asr.get_partial()
            if partial:
                if state == State.WAKE_LISTENING and self.dispatcher.has_wake_word(partial):
                    await self.asr.flush_final()
                    await self._send({"type": "asr_final", "text": partial})
                    await self.sm.transition(State.LISTENING, "唤醒成功，聆听中")
                    await self.asr.reset()
                else:
                    await self._send({"type": "asr_partial", "text": self.accumulated_text + partial})

    async def _handle_voice_end(self) -> None:
        self.voice_active = False
        await self._send({"type": "vad_event", "action": "voice_end", "text": "静默"})
        state = self.sm.state
        if state == State.WAKE_LISTENING:
            final = await self.asr.get_final() or await self.asr.flush_final()
            if final:
                await self._process_recognized_text(final, is_final=True)
        elif state == State.RECOGNIZING:
            final = await self.asr.get_final() or await self.asr.flush_final()
            if final:
                await self._process_recognized_text(final, is_final=True)
            else:
                await self.sm.transition(State.LISTENING, "聆听中，说\"说完了\"发送")
                await self._send({"type": "asr_partial", "text": self.accumulated_text})
        if self.interaction_mode == "chat" and self.pending_send_text and (not self._pending_send_task or self._pending_send_task.done()):
            self._pending_send_task = asyncio.create_task(self._send_after_silence())

    async def _handle_asr_result(self, data: dict) -> None:
        """Handle ASR results from client-side engine (Web Speech API)."""
        text = data.get("text", "").strip()
        is_final = data.get("is_final", False)
        if not text:
            return

        if not self._asr_start_time:
            self._asr_start_time = self._voice_start_time or time.time()

        await self.asr.receive_result(text, is_final)

        state = self.sm.state
        if state not in (State.WAKE_LISTENING, State.LISTENING, State.RECOGNIZING, State.PLAYING):
            return

        if is_final:
            asr_elapsed = time.time() - self._asr_start_time if self._asr_start_time else 0
            logger.info("ASR耗时: %.2fs | 文本: %s", asr_elapsed, text)
            await self._send({"type": "timing", "stage": "asr", "elapsed": round(asr_elapsed, 2)})
            self._asr_start_time = 0
            await self._process_recognized_text(text, is_final=True)
        else:
            if state == State.WAKE_LISTENING and self.dispatcher.has_wake_word(text):
                await self._send({"type": "asr_final", "text": text})
                await self.sm.transition(State.LISTENING, "唤醒成功，聆听中")
                await self.asr.reset()
            else:
                await self._send({"type": "asr_partial", "text": self.accumulated_text + text})

    async def _process_recognized_text(self, text: str, is_final: bool) -> None:
        state = self.sm.state

        if state == State.WAKE_LISTENING:
            if self.dispatcher.has_wake_word(text):
                await self._send({"type": "asr_final", "text": text})
                await self.sm.transition(State.LISTENING, "唤醒成功，聆听中")
                await self.asr.reset()
            return

        event = self.dispatcher.dispatch(text)
        command = event.action if event else CommandType.NONE
        cleaned_text = event.cleaned_text if event else text
        if event:
            await self._send({"type": "keyword", "action": event.action.value, "text": text})

        if command == CommandType.NONE and self.intent_classifier.enabled:
            intent_start = time.time()
            intent = await self.intent_classifier.classify(text, self.accumulated_text)
            intent_elapsed = time.time() - intent_start
            logger.info("意图判断耗时: %.2fs | 意图: %s | 文本: %s", intent_elapsed, intent.intent.value, text)
            await self._send({"type": "timing", "stage": "intent", "elapsed": round(intent_elapsed, 2)})
            await self._send({"type": "intent_result", "intent": intent.intent.value, "text": text, "reason": intent.reason})

            if intent.intent == IntentType.COMMAND:
                mapped_cmd = _COMMAND_SUBTYPE_MAP.get(intent.command_type, CommandType.NONE)
                if mapped_cmd != CommandType.NONE:
                    command = mapped_cmd
                    cleaned_text = ""
                    await self._send({"type": "keyword", "action": command.value, "text": text})
            elif intent.intent == IntentType.CANCEL:
                await self._send({"type": "asr_final", "text": text})
                await self.asr.reset()
                return
            elif intent.intent == IntentType.APPEND:
                pass
            elif intent.intent == IntentType.SEND:
                command = CommandType.SEND
                cleaned_text = text

        if command == CommandType.EXIT:
            await self._send({"type": "asr_final", "text": text})
            self.accumulated_text = ""
            self.pending_send_text = ""
            if self._pending_send_task and not self._pending_send_task.done():
                self._pending_send_task.cancel()
            await self.asr.reset()
            await self._send({"type": "playback_control", "action": "clear", "text": "退出对话，清空播放队列"})
            await self.sm.transition(State.WAKE_LISTENING, "对话退出，等待唤醒")
            return

        if command == CommandType.REPLAY:
            await self._send({"type": "asr_final", "text": text})
            self.accumulated_text = ""
            await self.asr.reset()
            if self.last_tts_text:
                await self._do_tts(self.last_tts_text)
            return

        if command == CommandType.PREV:
            await self._send({"type": "asr_final", "text": text})
            await self.asr.reset()
            await self._play_segment_offset(-1)
            return

        if command == CommandType.NEXT:
            await self._send({"type": "asr_final", "text": text})
            await self.asr.reset()
            await self._play_segment_offset(1)
            return

        if command == CommandType.PAUSE:
            await self._send({"type": "asr_final", "text": text})
            await self.asr.reset()
            await self._send({"type": "playback_control", "action": "pause", "text": "语音命令暂停播放"})
            await self.sm.transition(State.LISTENING, "播放暂停，继续聆听")
            return

        if command == CommandType.RESUME:
            await self._send({"type": "asr_final", "text": text})
            await self.asr.reset()
            await self._send({"type": "playback_control", "action": "resume", "text": "语音命令继续播放"})
            await self.sm.transition(State.LISTENING, "播放恢复，继续聆听")
            return

        if command == CommandType.CLEAR:
            await self._send({"type": "asr_final", "text": text})
            async with self._conversation_lock:
                self.chat_history.clear()
            self.accumulated_text = ""
            await self.asr.reset()
            await self._send({"type": "command_result", "action": "clear", "success": True})
            await self.sm.transition(State.LISTENING, "对话已清空，聆听中")
            return

        if command == CommandType.MODE_WORK:
            await self._send({"type": "asr_final", "text": text})
            self.interaction_mode = "work"
            await self.asr.reset()
            await self._send({"type": "mode_change", "mode": "work"})
            await self.sm.transition(State.LISTENING, "已切换工作模式，手动发送")
            return

        if command == CommandType.MODE_CHAT:
            await self._send({"type": "asr_final", "text": text})
            self.interaction_mode = "chat"
            await self.asr.reset()
            await self._send({"type": "mode_change", "mode": "chat"})
            await self.sm.transition(State.LISTENING, "已切换聊天模式，静默自动发送")
            return

        if command == CommandType.SEND:
            send_text = (self.accumulated_text + " " + cleaned_text).strip()
            self.accumulated_text = ""
            await self._send({"type": "asr_final", "text": send_text})
            if send_text:
                if self.interaction_mode == "work":
                    self.pending_send_text = ""
                    await self._send({"type": "track_update", "track": "input", "active": True, "text": "工作模式，直接发送"})
                    self._start_processing(send_text)
                else:
                    self.pending_send_text = send_text
                    await self._send({"type": "track_update", "track": "input", "active": True, "text": f"检测到发送词，等待静默 {SILENCE_TIMEOUT_S:.0f} 秒"})
                    if not self.voice_active:
                        self._pending_send_task = asyncio.create_task(self._send_after_silence())
            else:
                await self.sm.transition(State.LISTENING, "聆听中")
            return

        if self.pending_send_text:
            self.pending_send_text = (self.pending_send_text + " " + cleaned_text).strip()
            await self._send({"type": "asr_final", "text": self.pending_send_text})
            await self._send({"type": "track_update", "track": "input", "active": True, "text": "继续补充待发送内容"})
            return

        self.accumulated_text = (self.accumulated_text + " " + cleaned_text).strip()
        await self._send({"type": "asr_final", "text": self.accumulated_text})
        if self.sm.state == State.RECOGNIZING:
            await self.sm.transition(State.LISTENING, "聆听中，说\"说完了\"发送")

    async def _handle_text_input(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if self.sm.state == State.IDLE:
            await self.sm.force_state(State.LISTENING, "")
        self._start_processing(text)

    def _start_processing(self, text: str) -> None:
        task = asyncio.create_task(self._process_send(text))
        self._processing_tasks.add(task)
        task.add_done_callback(self._processing_tasks.discard)

    async def _send_after_silence(self) -> None:
        try:
            await asyncio.sleep(SILENCE_TIMEOUT_S)
            if self.voice_active or not self.pending_send_text:
                return
            text = self.pending_send_text
            self.pending_send_text = ""
            await self._send({"type": "track_update", "track": "input", "active": True, "text": f"静默 {SILENCE_TIMEOUT_S:.0f} 秒，自动发送"})
            self._start_processing(text)
            if self.sm.state == State.RECOGNIZING:
                await self.sm.transition(State.LISTENING, "聆听中，可继续说下一句")
        except asyncio.CancelledError:
            logger.debug("Pending send cancelled")

    async def _process_send(self, text: str) -> None:
        await self.asr.reset()
        await self._send({"type": "user_message", "text": text})
        await self._send({"type": "track_update", "track": "thinking", "active": True, "text": "AI 思考中"})

        agent_start = time.time()
        try:
            async with self._conversation_lock:
                history_snapshot = list(self.chat_history)

            self.tts_segments = []
            self.tts_segment_index = 0
            self.agent_response.start_streaming(agent_name="openclaw")
            first_token_time: float = 0
            tts_tasks: list[asyncio.Task] = []

            ordered_sender = asyncio.create_task(self._send_tts_in_order())

            async for token in self.llm.chat_stream(text, history_snapshot):
                if not first_token_time:
                    first_token_time = time.time()
                await self._send({"type": "ai_reply_delta", "text": token})
                new_segments = self.agent_response.feed_token(token)
                for seg in new_segments:
                    self.tts_segments.append(seg.cleaned_text)
                    task = asyncio.create_task(self._synthesize_segment(seg.cleaned_text, seg.index))
                    tts_tasks.append(task)

            last_seg = self.agent_response.finish_streaming()
            if last_seg:
                self.tts_segments.append(last_seg.cleaned_text)
                task = asyncio.create_task(self._synthesize_segment(last_seg.cleaned_text, last_seg.index))
                tts_tasks.append(task)

            self.agent_response.notify_streaming_done()

            if tts_tasks:
                await asyncio.gather(*tts_tasks, return_exceptions=True)

            await ordered_sender

            full_reply = self.agent_response.full_text
            agent_elapsed = time.time() - agent_start
            first_token_elapsed = first_token_time - agent_start if first_token_time else agent_elapsed
            logger.info("Agent耗时: %.2fs (首token: %.2fs) | 文本: %s", agent_elapsed, first_token_elapsed, full_reply[:60])
            await self._send({"type": "timing", "stage": "agent", "elapsed": round(agent_elapsed, 2), "first_token": round(first_token_elapsed, 2)})

            self.agent_response.is_playing = True

            async with self._conversation_lock:
                self.chat_history.append({"role": "user", "content": text})
                self.chat_history.append({"role": "assistant", "content": full_reply})
                if len(self.chat_history) > 40:
                    self.chat_history = self.chat_history[-40:]

            await self._send({"type": "ai_reply", "text": full_reply})
            self.last_tts_text = full_reply
            await self._send_playback_status()
        except asyncio.CancelledError:
            logger.info("Processing cancelled for: %s", text[:20])
        except Exception as e:
            logger.error("LLM/TTS error: %s", e, exc_info=True)
            await self._send({"type": "error", "message": str(e)})
            await self.sm.transition(State.LISTENING, "出错，继续聆听")
        finally:
            await self._send({"type": "track_update", "track": "thinking", "active": False, "text": "AI 处理结束"})

    async def _synthesize_segment(self, text: str, index: int) -> None:
        """Synthesize TTS audio for a segment (parallel-safe, does not send to client)."""
        tts_start = time.time()
        try:
            audio_data = await self.tts.synthesize(text)
            tts_elapsed = time.time() - tts_start
            if not audio_data:
                logger.warning("TTS empty result for segment %d: %s", index + 1, text[:30])
                self.agent_response.mark_segment_ready(index, "", "mp3")
                return
            logger.info("TTS耗时: %.2fs | 分段%d: %s", tts_elapsed, index + 1, text[:30])
            await self._send({"type": "timing", "stage": "tts", "elapsed": round(tts_elapsed, 2), "segment_index": index})
            audio_b64 = base64.b64encode(audio_data).decode()
            self.agent_response.mark_segment_ready(index, audio_b64, "mp3")
        except Exception as e:
            logger.error("TTS segment %d error: %s", index, e)
            self.agent_response.mark_segment_ready(index, "", "mp3")

    async def _send_tts_in_order(self) -> None:
        """Send TTS audio segments to client strictly in seq order."""
        while True:
            seg = await self.agent_response.wait_for_next_ready()
            if seg is None:
                break
            if not seg.audio_b64:
                continue
            await self._send({"type": "track_update", "track": "playing", "active": True, "text": f"TTS 分段 {seg.seq + 1}"})
            await self._send({
                "type": "tts_audio",
                "data": seg.audio_b64,
                "format": seg.format,
                "segment_index": seg.seq,
                "segment_text": seg.cleaned_text,
            })

    async def _do_tts_segment(self, text: str, index: int) -> None:
        """Synthesize and send a single segment immediately (used by prev/next/replay)."""
        await self._send({"type": "track_update", "track": "playing", "active": True, "text": f"TTS 分段 {index + 1}"})
        tts_start = time.time()
        try:
            audio_data = await self.tts.synthesize(text)
            tts_elapsed = time.time() - tts_start
            if not audio_data:
                logger.warning("TTS empty result for segment %d: %s", index + 1, text[:30])
                return
            logger.info("TTS耗时: %.2fs | 分段%d: %s", tts_elapsed, index + 1, text[:30])
            await self._send({"type": "timing", "stage": "tts", "elapsed": round(tts_elapsed, 2), "segment_index": index})
            audio_b64 = base64.b64encode(audio_data).decode()
            self.agent_response.mark_segment_ready(index, audio_b64, "mp3")
            await self._send({
                "type": "tts_audio",
                "data": audio_b64,
                "format": "mp3",
                "segment_index": index,
                "segment_text": text,
            })
        except Exception as e:
            logger.error("TTS segment error: %s", e)
            await self._send({"type": "error", "message": f"TTS failed: {e}"})

    async def _do_tts(self, text: str) -> None:
        """Fallback: synthesize full text as single segment (used by replay)."""
        await self._send({"type": "track_update", "track": "playing", "active": True, "text": "TTS 已入队"})
        try:
            audio_data = await self.tts.synthesize(text)
            audio_b64 = base64.b64encode(audio_data).decode()
            await self._send({"type": "tts_audio", "data": audio_b64, "format": "mp3"})
        except Exception as e:
            logger.error("TTS error: %s", e)
            await self._send({"type": "error", "message": f"TTS failed: {e}"})
            await self._send({"type": "track_update", "track": "playing", "active": False, "text": "TTS 出错"})

    async def _play_segment_offset(self, offset: int) -> None:
        """Play previous or next TTS segment."""
        if not self.tts_segments:
            await self._send({"type": "error", "message": "没有可播放的分段"})
            return
        await self._send({"type": "playback_control", "action": "stop_current", "text": "切换分段"})
        new_index = self.tts_segment_index + offset
        new_index = max(0, min(new_index, len(self.tts_segments) - 1))
        self.tts_segment_index = new_index
        self.agent_response.current_index = new_index
        seg = self.tts_segments[new_index]
        await self._send({"type": "keyword", "action": "segment_jump", "text": f"第 {new_index + 1}/{len(self.tts_segments)} 句: {seg}"})
        await self._do_tts_segment(seg, new_index)
        await self._send_playback_status()

    async def _handle_tts_playback_done(self) -> None:
        if self.tts_segment_index < len(self.tts_segments) - 1:
            self.tts_segment_index += 1
        self.agent_response.current_index = self.tts_segment_index
        await self._send({"type": "track_update", "track": "playing", "active": False, "text": "播报完成"})
        await self._send_playback_status()

    async def _handle_playback_command(self, data: dict) -> None:
        """Handle playback commands from the frontend UI controls."""
        action = data.get("action", "")
        cmd_map = {
            "pause": PlaybackCommand.PAUSE,
            "resume": PlaybackCommand.RESUME,
            "prev": PlaybackCommand.PREV,
            "next": PlaybackCommand.NEXT,
            "replay": PlaybackCommand.REPLAY,
            "clear": PlaybackCommand.CLEAR,
        }
        cmd = cmd_map.get(action)
        if not cmd:
            await self._send({"type": "error", "message": f"Unknown playback command: {action}"})
            return

        result = self.agent_response.execute_command(cmd)
        if result["action"] == "play_segment":
            index = result["index"]
            self.tts_segment_index = index
        elif result["action"] in ("pause", "resume", "clear"):
            await self._send({"type": "playback_control", "action": result["action"], "text": f"UI控制: {action}"})

        await self._send_playback_status()

    async def _send_playback_status(self) -> None:
        """Send current playback status to client."""
        status = self.agent_response.to_status()
        await self._send({
            "type": "playback_status",
            "total_segments": status["total_segments"],
            "current_index": status["current_index"],
            "is_paused": status["is_paused"],
            "text": status["current_text"],
        })


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    session = Session(ws)
    await session.initialize()
    logger.info("WebSocket client connected")

    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "message": "Invalid JSON"})
                continue
            await session.handle_message(data)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error("WebSocket error: %s", e)
    finally:
        await session.cleanup()


@app.websocket("/ws/asr")
async def asr_proxy_endpoint(ws: WebSocket):
    """Proxy WebSocket for Volcano Engine ASR (binary protocol).

    Browser sends: JSON text (config), binary PCM audio frames, JSON {"signal":"end"}.
    Backend wraps them into Volcano's binary protocol and relays responses back as JSON.
    """
    await ws.accept()

    if not VOLCANO_ASR_APP_KEY or not VOLCANO_ASR_ACCESS_KEY:
        await ws.send_json({"error": "Volcano ASR not configured (missing APP_KEY or ACCESS_KEY)"})
        await ws.close()
        return

    import uuid, gzip, struct
    try:
        import websockets
    except ImportError:
        await ws.send_json({"error": "websockets package not installed. Run: pip install websockets"})
        await ws.close()
        return

    connect_id = str(uuid.uuid4())
    headers = {
        "X-Api-App-Key": VOLCANO_ASR_APP_KEY,
        "X-Api-Access-Key": VOLCANO_ASR_ACCESS_KEY,
        "X-Api-Resource-Id": VOLCANO_ASR_RESOURCE_ID,
        "X-Api-Connect-Id": connect_id,
    }

    def build_header(msg_type: int, flags: int, serialization: int, compression: int) -> bytes:
        b0 = 0x11  # version=1, header_size=1 (4 bytes)
        b1 = (msg_type << 4) | (flags & 0x0F)
        b2 = (serialization << 4) | (compression & 0x0F)
        b3 = 0x00
        return bytes([b0, b1, b2, b3])

    def build_full_client_request(payload_json: str, use_gzip: bool = True) -> bytes:
        payload_bytes = payload_json.encode("utf-8")
        compression = 0x01 if use_gzip else 0x00
        if use_gzip:
            payload_bytes = gzip.compress(payload_bytes)
        header = build_header(msg_type=0x01, flags=0x00, serialization=0x01, compression=compression)
        return header + struct.pack(">I", len(payload_bytes)) + payload_bytes

    def build_audio_request(audio_data: bytes, is_last: bool = False, use_gzip: bool = False) -> bytes:
        compression = 0x01 if use_gzip else 0x00
        payload = gzip.compress(audio_data) if use_gzip else audio_data
        flags = 0x02 if is_last else 0x00
        header = build_header(msg_type=0x02, flags=flags, serialization=0x00, compression=compression)
        return header + struct.pack(">I", len(payload)) + payload

    def parse_server_response(data: bytes) -> dict:
        if len(data) < 4:
            return {"error": "Response too short"}
        header = data[0:4]
        msg_type = (header[1] >> 4) & 0x0F
        flags = header[1] & 0x0F
        serialization = (header[2] >> 4) & 0x0F
        compression = header[2] & 0x0F

        if msg_type == 0x0F:  # error
            if len(data) < 12:
                return {"error": "Malformed error response"}
            error_code = struct.unpack(">I", data[4:8])[0]
            error_size = struct.unpack(">I", data[8:12])[0]
            error_msg = data[12:12+error_size].decode("utf-8", errors="replace")
            return {"error": error_msg, "error_code": error_code}

        if msg_type == 0x09:  # full server response
            offset = 4
            # sequence number (4 bytes)
            if len(data) < offset + 4:
                return {"error": "Missing sequence"}
            sequence = struct.unpack(">i", data[offset:offset+4])[0]
            offset += 4
            # payload size
            if len(data) < offset + 4:
                return {"error": "Missing payload size"}
            payload_size = struct.unpack(">I", data[offset:offset+4])[0]
            offset += 4
            payload_bytes = data[offset:offset+payload_size]
            if compression == 0x01:
                payload_bytes = gzip.decompress(payload_bytes)
            if serialization == 0x01:
                import json as json_mod
                try:
                    result = json_mod.loads(payload_bytes)
                    result["_sequence"] = sequence
                    result["_is_last"] = (flags & 0x02) != 0
                    return result
                except Exception:
                    return {"error": "Failed to parse JSON payload", "_sequence": sequence}
            return {"_raw": payload_bytes.decode("utf-8", errors="replace"), "_sequence": sequence}

        return {"error": f"Unknown message type: {msg_type}"}

    logger.info("ASR proxy: connecting to Volcano (%s)", VOLCANO_ASR_WS_URL)

    try:
        async with websockets.connect(
            VOLCANO_ASR_WS_URL,
            additional_headers=headers,
            max_size=10 * 1024 * 1024,
        ) as volcano_ws:
            logger.info("ASR proxy: connected to Volcano (connect_id=%s)", connect_id)
            await ws.send_json({"type": "connected", "connect_id": connect_id})

            async def relay_from_volcano():
                try:
                    async for msg in volcano_ws:
                        if isinstance(msg, bytes):
                            parsed = parse_server_response(msg)
                            if "error" in parsed:
                                logger.warning("ASR proxy volcano error: %s", parsed)
                                await ws.send_json({"error": parsed.get("error", "Unknown error")})
                            else:
                                result = parsed.get("result", {})
                                utterances = result.get("utterances", [])
                                text = result.get("text", "")
                                resp = {
                                    "payload_msg": {"result": {"text": text, "utterances": utterances}},
                                    "header": {
                                        "status_code": 0,
                                        "message_type": "full_server_response",
                                    },
                                }
                                await ws.send_json(resp)
                        else:
                            logger.debug("ASR proxy volcano text msg: %s", str(msg)[:100])
                except websockets.ConnectionClosed as e:
                    logger.info("ASR proxy: volcano closed (code=%s reason=%s)", e.code, e.reason)
                except Exception as e:
                    logger.debug("ASR proxy volcano->client error: %s", e)

            async def relay_from_browser():
                config_sent = False
                try:
                    while True:
                        data = await ws.receive()
                        if data["type"] == "websocket.disconnect":
                            logger.info("ASR proxy: browser disconnected")
                            break
                        if "text" in data:
                            text_data = data["text"]
                            try:
                                msg = json.loads(text_data)
                            except json.JSONDecodeError:
                                continue
                            if msg.get("signal") == "end":
                                frame = build_audio_request(b"", is_last=True)
                                await volcano_ws.send(frame)
                                logger.info("ASR proxy: sent last audio frame")
                            elif not config_sent:
                                frame = build_full_client_request(text_data)
                                await volcano_ws.send(frame)
                                config_sent = True
                                logger.info("ASR proxy: sent config frame (%d bytes)", len(frame))
                        elif "bytes" in data:
                            audio_bytes = data["bytes"]
                            frame = build_audio_request(audio_bytes, is_last=False)
                            await volcano_ws.send(frame)
                except WebSocketDisconnect:
                    logger.info("ASR proxy: browser WebSocketDisconnect")
                except Exception as e:
                    logger.debug("ASR proxy client->volcano error: %s", e)

            volcano_task = asyncio.create_task(relay_from_volcano())
            browser_task = asyncio.create_task(relay_from_browser())

            done, pending = await asyncio.wait(
                [volcano_task, browser_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()

    except Exception as e:
        logger.error("ASR proxy connection error: %s", e)
        try:
            await ws.send_json({"error": f"Volcano connection failed: {e}"})
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass
        logger.info("ASR proxy: session ended")


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok", "service": "crayfish-voice-backend"})


if DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")


@app.get("/")
async def index():
    index_file = DIST_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return JSONResponse({"status": "ok", "message": "Run npm run build to generate the frontend."})


@app.get("/{path:path}")
async def spa_fallback(path: str):
    target = DIST_DIR / path
    if target.is_file():
        return FileResponse(target)
    index_file = DIST_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return JSONResponse({"status": "ok", "message": "Frontend build not found."}, status_code=404)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "3456"))
    host = os.environ.get("HOST", "0.0.0.0")
    logger.info("Starting Crayfish backend at http://localhost:%d/", port)
    uvicorn.run(app, host=host, port=port)
