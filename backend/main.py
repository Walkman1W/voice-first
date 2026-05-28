import base64
import json
import logging
import os
import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from state_machine import StateMachine, State
from command_parser import parse_command, is_wake_word, CommandType
from engines import VoskASREngine, EdgeTTSEngine, OpenClawLLMEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("crayfish")

app = FastAPI(title="Crayfish Voice Assistant Backend")

GATEWAY_URL = os.environ.get("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
GATEWAY_TOKEN = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "89511f3f33f4255def0cfc032175a56bcb2c1c1e09dad63e")
TTS_VOICE = os.environ.get("TTS_VOICE", "zh-CN-XiaoxiaoNeural")
VOSK_MODEL = os.environ.get("VOSK_MODEL_PATH", None)


class Session:
    """Per-WebSocket connection session managing engines and state."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.sm = StateMachine()
        self.asr = VoskASREngine(model_path=VOSK_MODEL)
        self.tts = EdgeTTSEngine(voice=TTS_VOICE)
        self.llm = OpenClawLLMEngine(base_url=GATEWAY_URL, token=GATEWAY_TOKEN)
        self.chat_history: list[dict] = []
        self.accumulated_text = ""
        self.last_tts_text = ""
        self._processing_task: asyncio.Task | None = None
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
            logger.info("Session initialized with ASR engine")
        except FileNotFoundError as e:
            logger.warning("ASR not available: %s", e)
            await self._send({"type": "error", "message": f"ASR unavailable: {e}"})
        except ImportError:
            logger.warning("vosk package not installed, ASR disabled")
            await self._send({"type": "error", "message": "vosk not installed, ASR disabled"})

    async def cleanup(self) -> None:
        if self._processing_task and not self._processing_task.done():
            self._processing_task.cancel()
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
            if self._processing_task and not self._processing_task.done():
                self._processing_task.cancel()
                self._processing_task = None
            await self.sm.force_state(State.IDLE, "已停止")
            await self.asr.reset()
            self.accumulated_text = ""
            await self._send({"type": "command_result", "action": action, "success": True})
        elif action == "clear":
            self.chat_history.clear()
            await self._send({"type": "command_result", "action": action, "success": True})
        else:
            await self._send({"type": "error", "message": f"Unknown command: {action}"})

    async def _handle_voice_start(self) -> None:
        state = self.sm.state
        if state == State.WAKE_LISTENING:
            pass
        elif state == State.LISTENING:
            await self.sm.transition(State.RECOGNIZING, "识别中")
            await self.asr.reset()

    async def _handle_audio(self, data: dict) -> None:
        state = self.sm.state
        if state not in (State.WAKE_LISTENING, State.LISTENING, State.RECOGNIZING):
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
                if state == State.WAKE_LISTENING and is_wake_word(partial):
                    await self.asr.flush_final()
                    await self._send({"type": "asr_final", "text": partial})
                    await self.sm.transition(State.LISTENING, "唤醒成功，聆听中")
                    await self.asr.reset()
                else:
                    await self._send({"type": "asr_partial", "text": self.accumulated_text + partial})

    async def _handle_voice_end(self) -> None:
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

    async def _process_recognized_text(self, text: str, is_final: bool) -> None:
        state = self.sm.state

        if state == State.WAKE_LISTENING:
            if is_wake_word(text):
                await self._send({"type": "asr_final", "text": text})
                await self.sm.transition(State.LISTENING, "唤醒成功，聆听中")
                await self.asr.reset()
            return

        result = parse_command(text)

        if result.command == CommandType.EXIT:
            await self._send({"type": "asr_final", "text": text})
            self.accumulated_text = ""
            await self.asr.reset()
            await self.sm.transition(State.WAKE_LISTENING, "对话退出，等待唤醒")
            return

        if result.command == CommandType.REPLAY:
            await self._send({"type": "asr_final", "text": text})
            self.accumulated_text = ""
            await self.asr.reset()
            if self.last_tts_text:
                await self._do_tts(self.last_tts_text)
            return

        if result.command == CommandType.CLEAR:
            await self._send({"type": "asr_final", "text": text})
            self.chat_history.clear()
            self.accumulated_text = ""
            await self.asr.reset()
            await self._send({"type": "command_result", "action": "clear", "success": True})
            await self.sm.transition(State.LISTENING, "对话已清空，聆听中")
            return

        if result.command == CommandType.SEND:
            send_text = (self.accumulated_text + " " + result.cleaned_text).strip()
            self.accumulated_text = ""
            await self._send({"type": "asr_final", "text": send_text})
            if send_text:
                self._start_processing(send_text)
            else:
                await self.sm.transition(State.LISTENING, "聆听中")
            return

        self.accumulated_text += text
        await self._send({"type": "asr_final", "text": self.accumulated_text})

    async def _handle_text_input(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if self.sm.state == State.IDLE:
            await self.sm.force_state(State.LISTENING, "")
        self._start_processing(text)

    def _start_processing(self, text: str) -> None:
        if self._processing_task and not self._processing_task.done():
            self._processing_task.cancel()
        self._processing_task = asyncio.create_task(self._process_send(text))

    async def _process_send(self, text: str) -> None:
        await self.asr.reset()
        await self._send({"type": "user_message", "text": text})
        await self.sm.transition(State.THINKING, "AI 思考中")

        try:
            reply = await self.llm.chat(text, self.chat_history)
            self.chat_history.append({"role": "user", "content": text})
            self.chat_history.append({"role": "assistant", "content": reply})
            if len(self.chat_history) > 40:
                self.chat_history = self.chat_history[-40:]

            await self._send({"type": "ai_reply", "text": reply})
            self.last_tts_text = reply
            await self._do_tts(reply)
        except asyncio.CancelledError:
            logger.info("Processing cancelled for: %s", text[:20])
        except Exception as e:
            logger.error("LLM/TTS error: %s", e, exc_info=True)
            await self._send({"type": "error", "message": str(e)})
            await self.sm.transition(State.LISTENING, "出错，继续聆听")

    async def _do_tts(self, text: str) -> None:
        await self.sm.transition(State.PLAYING, "播报中")
        try:
            audio_data = await self.tts.synthesize(text)
            audio_b64 = base64.b64encode(audio_data).decode()
            await self._send({"type": "tts_audio", "data": audio_b64, "format": "mp3"})
        except Exception as e:
            logger.error("TTS error: %s", e)
            await self._send({"type": "error", "message": f"TTS failed: {e}"})
            if self.sm.state == State.PLAYING:
                await self.sm.transition(State.LISTENING, "TTS出错，继续聆听")

    async def _handle_tts_playback_done(self) -> None:
        if self.sm.state == State.PLAYING:
            await self.sm.transition(State.LISTENING, "播报完成，聆听中")


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


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8765"))
    logger.info("Starting Crayfish backend on port %d", port)
    uvicorn.run(app, host="0.0.0.0", port=port)
