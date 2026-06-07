import asyncio
import logging
from enum import Enum
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


class State(str, Enum):
    IDLE = "idle"
    WAKE_LISTENING = "wake_listening"
    LISTENING = "listening"
    RECOGNIZING = "recognizing"
    THINKING = "thinking"
    PLAYING = "playing"


VALID_TRANSITIONS: dict[State, set[State]] = {
    State.IDLE: {State.WAKE_LISTENING, State.LISTENING, State.THINKING},
    State.WAKE_LISTENING: {State.LISTENING, State.IDLE},
    State.LISTENING: {State.RECOGNIZING, State.THINKING, State.PLAYING, State.IDLE, State.WAKE_LISTENING},
    State.RECOGNIZING: {State.THINKING, State.LISTENING, State.IDLE, State.WAKE_LISTENING},
    State.THINKING: {State.PLAYING, State.LISTENING, State.IDLE},
    State.PLAYING: {State.LISTENING, State.IDLE, State.WAKE_LISTENING},
}

StateChangeCallback = Callable[[State, str], Awaitable[None]]


class StateMachine:
    def __init__(self):
        self._state = State.IDLE
        self._callbacks: list[StateChangeCallback] = []
        self._lock = asyncio.Lock()

    @property
    def state(self) -> State:
        return self._state

    def on_state_change(self, callback: StateChangeCallback) -> None:
        self._callbacks.append(callback)

    async def transition(self, new_state: State, description: str = "") -> bool:
        async with self._lock:
            if new_state == self._state:
                return True
            if new_state not in VALID_TRANSITIONS.get(self._state, set()):
                logger.warning(
                    "Invalid transition: %s -> %s", self._state, new_state
                )
                return False
            old_state = self._state
            self._state = new_state
            logger.info("%s -> %s (%s)", old_state, new_state, description)

        for cb in self._callbacks:
            try:
                await cb(new_state, description)
            except Exception as e:
                logger.error("State change callback error: %s", e)
        return True

    async def force_state(self, new_state: State, description: str = "") -> None:
        async with self._lock:
            old_state = self._state
            self._state = new_state
            logger.info("FORCE %s -> %s (%s)", old_state, new_state, description)

        for cb in self._callbacks:
            try:
                await cb(new_state, description)
            except Exception as e:
                logger.error("State change callback error: %s", e)
