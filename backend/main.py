import base64
import json
import logging
import os
import asyncio
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from state_machine import StateMachine, State
from command_parser import CommandType
from keyword_dispatcher import KeywordDispatcher
from text_segmenter import TextSegmenter
from engines import EdgeTTSEngine, OpenClawLLMEngine, create_asr_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("crayfish")

app = FastAPI(title="Crayfish Voice Assistant Backend")
ROOT_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT_DIR / "dist"

GATEWAY_URL = os.environ.get("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
GATEWAY_TOKEN = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "89511f3f33f4255def0cfc032175a56bcb2c1c1e09dad63e")
TTS_VOICE = os.environ.get("TTS_VOICE", "zh-CN-XiaoxiaoNeural")
VOSK_MODEL = os.environ.get("VOSK_MODEL_PATH", None)
ASR_ENGINE_NAME = os.environ.get("ASR_ENGINE", "edge")


class Session:
    """Per-WebSocket connection session managing engines and state."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.sm = StateMachine()
        self.asr = create_asr_engine(ASR_ENGINE_NAME, model_path=VOSK_MODEL)
        self.tts = EdgeTTSEngine(voice=TTS_VOICE)
        self.llm = OpenClawLLMEngine(base_url=GATEWAY_URL, token=GATEWAY_TOKEN)
        self.dispatcher = KeywordDispatcher()
        self.chat_history: list[dict] = []
        self.accumulated_text = ""
        self.last_tts_text = ""
        self.voice_active = False
        self.pending_send_text = ""
        self._processing_tasks: set[asyncio.Task] = set()
        self._pending_send_task: asyncio.Task | None = None
        self._conversation_lock = asyncio.Lock()
        self.tts_segments: list[str] = []
        self.tts_segment_index: int = 0
        self.sm.on_state_change(self._on_state_change)

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
        if self.pending_send_text and (not self._pending_send_task or self._pending_send_task.done()):
            self._pending_send_task = asyncio.create_task(self._send_after_silence())

    async def _handle_asr_result(self, data: dict) -> None:
        """Handle ASR results from client-side engine (Web Speech API)."""
        text = data.get("text", "").strip()
        is_final = data.get("is_final", False)
        if not text:
            return

        await self.asr.receive_result(text, is_final)

        state = self.sm.state
        if state not in (State.WAKE_LISTENING, State.LISTENING, State.RECOGNIZING, State.PLAYING):
            return

        if is_final:
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

        if command == CommandType.SEND:
            send_text = (self.accumulated_text + " " + cleaned_text).strip()
            self.accumulated_text = ""
            self.pending_send_text = send_text
            await self._send({"type": "asr_final", "text": send_text})
            if send_text:
                await self._send({"type": "track_update", "track": "input", "active": True, "text": "检测到发送词，等待静默 2 秒"})
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
            await asyncio.sleep(2)
            if self.voice_active or not self.pending_send_text:
                return
            text = self.pending_send_text
            self.pending_send_text = ""
            await self._send({"type": "track_update", "track": "input", "active": True, "text": "静默 2 秒，确认发送"})
            self._start_processing(text)
            if self.sm.state == State.RECOGNIZING:
                await self.sm.transition(State.LISTENING, "聆听中，可继续说下一句")
        except asyncio.CancelledError:
            logger.debug("Pending send cancelled")

    async def _process_send(self, text: str) -> None:
        await self.asr.reset()
        await self._send({"type": "user_message", "text": text})
        await self._send({"type": "track_update", "track": "thinking", "active": True, "text": "AI 思考中"})

        try:
            async with self._conversation_lock:
                history_snapshot = list(self.chat_history)

            segmenter = TextSegmenter()
            full_reply = ""
            self.tts_segments = []
            self.tts_segment_index = 0

            async for token in self.llm.chat_stream(text, history_snapshot):
                full_reply += token
                await self._send({"type": "ai_reply_delta", "text": token})
                segments = segmenter.feed(token)
                for seg in segments:
                    self.tts_segments.append(seg)
                    await self._do_tts_segment(seg, len(self.tts_segments) - 1)

            remaining = segmenter.flush()
            if remaining:
                self.tts_segments.append(remaining)
                await self._do_tts_segment(remaining, len(self.tts_segments) - 1)

            async with self._conversation_lock:
                self.chat_history.append({"role": "user", "content": text})
                self.chat_history.append({"role": "assistant", "content": full_reply})
                if len(self.chat_history) > 40:
                    self.chat_history = self.chat_history[-40:]

            await self._send({"type": "ai_reply", "text": full_reply})
            self.last_tts_text = full_reply
        except asyncio.CancelledError:
            logger.info("Processing cancelled for: %s", text[:20])
        except Exception as e:
            logger.error("LLM/TTS error: %s", e, exc_info=True)
            await self._send({"type": "error", "message": str(e)})
            await self.sm.transition(State.LISTENING, "出错，继续聆听")
        finally:
            await self._send({"type": "track_update", "track": "thinking", "active": False, "text": "AI 处理结束"})

    async def _do_tts_segment(self, text: str, index: int) -> None:
        await self._send({"type": "track_update", "track": "playing", "active": True, "text": f"TTS 分段 {index + 1}"})
        try:
            audio_data = await self.tts.synthesize(text)
            audio_b64 = base64.b64encode(audio_data).decode()
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
        await self._send({"type": "playback_control", "action": "clear", "text": "切换分段"})
        new_index = self.tts_segment_index + offset
        new_index = max(0, min(new_index, len(self.tts_segments) - 1))
        self.tts_segment_index = new_index
        seg = self.tts_segments[new_index]
        await self._send({"type": "keyword", "action": "segment_jump", "text": f"第 {new_index + 1}/{len(self.tts_segments)} 句: {seg}"})
        await self._do_tts_segment(seg, new_index)

    async def _handle_tts_playback_done(self) -> None:
        if self.tts_segment_index < len(self.tts_segments) - 1:
            self.tts_segment_index += 1
        await self._send({"type": "track_update", "track": "playing", "active": False, "text": "播报完成"})


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
    port = int(os.environ.get("PORT", "8765"))
    host = os.environ.get("HOST", "127.0.0.1")
    logger.info("Starting Crayfish backend at http://localhost:%d/", port)
    logger.info("Binding host: %s", host)
    uvicorn.run(app, host=host, port=port)
