"""WebSocket commands and desktop-facing runtime projection."""

import asyncio
import copy
import time
from dataclasses import asdict
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from lalk.observability import (
    AgentRequestEvent,
    AgentTextEvent,
    ComponentEvent,
    ErrorEvent,
    InputLevelEvent,
    InputSource,
    MetricsEvent,
    PlaybackEvent,
    PlaybackState,
    SessionEvent,
    SessionState,
    SpeechEvent,
    SpeechState,
    SynthesisEvent,
    SynthesisState,
    ToolCallFinishedEvent,
    ToolCallStartedEvent,
    TranscriptEvent,
    TurnEvent,
    TurnState,
    UserInputEvent,
    VoiceEvent,
)

from .proactive import ProactiveRequest

_EVENT_TYPES: dict[type[VoiceEvent], str] = {
    SessionEvent: "session.state",
    ComponentEvent: "component.state",
    InputLevelEvent: "audio.input_level",
    SpeechEvent: "speech.state",
    TranscriptEvent: "transcript.update",
    UserInputEvent: "turn.input",
    TurnEvent: "turn.state",
    AgentRequestEvent: "agent.request",
    AgentTextEvent: "assistant.text.delta",
    ToolCallStartedEvent: "tool.started",
    ToolCallFinishedEvent: "tool.finished",
    SynthesisEvent: "synthesis.state",
    PlaybackEvent: "playback.state",
    MetricsEvent: "turn.metrics",
    ErrorEvent: "runtime.error",
}


class _Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)


class StartCommand(_Command):
    type: Literal["session.start"]


class StopCommand(_Command):
    type: Literal["session.stop"]


class InterruptCommand(_Command):
    type: Literal["turn.interrupt"]


class SubmitTextCommand(_Command):
    type: Literal["turn.submit_text"]
    text: str


class NewConversationCommand(_Command):
    type: Literal["conversation.new"]


class AnswerProactiveCommand(_Command):
    type: Literal["proactive.answer"]
    request_id: str = Field(min_length=1)


class DismissProactiveCommand(_Command):
    type: Literal["proactive.dismiss"]
    request_id: str = Field(min_length=1)


class SnoozeProactiveCommand(_Command):
    type: Literal["proactive.snooze"]
    request_id: str = Field(min_length=1)
    minutes: int = Field(gt=0, le=1_440)


Command = Annotated[
    StartCommand
    | StopCommand
    | InterruptCommand
    | SubmitTextCommand
    | NewConversationCommand
    | AnswerProactiveCommand
    | DismissProactiveCommand
    | SnoozeProactiveCommand,
    Field(discriminator="type"),
]
COMMAND_ADAPTER = TypeAdapter(Command)


class RuntimeView:
    """Project ordered SDK events into a reconnectable frontend snapshot."""

    def __init__(
        self,
        runtime_state: str,
        *,
        turns: list[dict[str, Any]] | None = None,
    ) -> None:
        self.runtime_state = runtime_state
        self.stage = "idle" if runtime_state == "idle" else runtime_state
        self.stage_started_at: float | None = None
        self.session_id: str | None = None
        self.sequence = 0
        self.components: dict[str, dict[str, Any]] = {}
        self.input_level = 0.0
        self.input_gate: dict[str, Any] | None = None
        self.live_transcript: dict[str, Any] | None = None
        self.turns = copy.deepcopy(turns) if turns is not None else []
        self.error: dict[str, Any] | None = None
        self.proactive_offer: dict[str, Any] | None = None

        self._turns_by_id: dict[int, dict[str, Any]] = {}
        self._active_turn_id: int | None = None
        self._active_tool_ids: set[str] = set()
        self._speech_active = False
        self._awaiting_transcript = False
        self._synthesis_active = False
        self._playback_active = False
        self._client_queue: asyncio.Queue[dict[str, Any]] | None = None

    def set_runtime_state(
        self,
        state: str,
        *,
        error: dict[str, Any] | None = None,
    ) -> None:
        timestamp = time.time()
        self.runtime_state = state
        self.error = error
        self._update_stage(timestamp)
        self._publish(
            "runtime.state",
            {"state": state, "error": error},
            timestamp=timestamp,
        )

    def on_event(self, event: VoiceEvent) -> None:
        """Consume one Lalk event without blocking its dispatcher."""

        self._apply(event)
        if isinstance(event, AgentRequestEvent):
            data = {
                "session_id": event.session_id,
                "turn_id": event.turn_id,
                "message_count": len(event.messages),
            }
            timestamp = event.timestamp
        elif isinstance(event, UserInputEvent) and event.source in {
            InputSource.OPENING,
            InputSource.PROACTIVE,
            InputSource.FOLLOWUP,
        }:
            data = asdict(event)
            data["text"] = ""
            timestamp = data.pop("timestamp")
        else:
            data = asdict(event)
            timestamp = data.pop("timestamp")
        self._publish(_EVENT_TYPES[type(event)], data, timestamp=timestamp)

    def set_proactive_offer(self, request: ProactiveRequest | None) -> None:
        """Publish the one desktop offer currently awaiting a user decision."""

        self.proactive_offer = (
            {
                "id": request.id,
                "title": request.title,
                "available_at": request.available_at.isoformat(),
                "state": request.state.value,
            }
            if request is not None
            else None
        )
        self._publish(
            "proactive.offer",
            {"offer": copy.deepcopy(self.proactive_offer)},
            timestamp=time.time(),
        )

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        if self._client_queue is not None:
            raise RuntimeError("A runtime WebSocket is already connected")
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=512)
        self._client_queue = queue
        queue.put_nowait({"type": "snapshot", "data": self.snapshot()})
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        if self._client_queue is queue:
            self._client_queue = None

    def send_command_result(
        self,
        command_id: str,
        *,
        ok: bool,
        data: dict[str, Any] | None = None,
        error: dict[str, str] | None = None,
    ) -> None:
        message: dict[str, Any] = {
            "type": "command.result",
            "id": command_id,
            "ok": ok,
        }
        if data is not None:
            message["data"] = data
        if error is not None:
            message["error"] = error
        self._send(message)

    def snapshot(self) -> dict[str, Any]:
        return {
            "runtime_state": self.runtime_state,
            "stage": self.stage,
            "stage_started_at": self.stage_started_at,
            "session_id": self.session_id,
            "sequence": self.sequence,
            "components": copy.deepcopy(self.components),
            "input_level": self.input_level,
            "input_gate": copy.deepcopy(self.input_gate),
            "live_transcript": copy.deepcopy(self.live_transcript),
            "turns": copy.deepcopy(self.turns),
            "error": copy.deepcopy(self.error),
            "proactive_offer": copy.deepcopy(self.proactive_offer),
        }

    def persisted_turns(self) -> list[dict[str, Any]]:
        """Return conversation turns safe for persistence."""

        return copy.deepcopy(
            [
                turn
                for turn in self.turns
                if turn["state"] in {"completed", "interrupted", "failed"}
            ]
        )

    def new_conversation(self) -> None:
        """Clear the projection for a newly created conversation."""

        self.live_transcript = None
        self.turns.clear()
        self._turns_by_id.clear()

    def _apply(self, event: VoiceEvent) -> None:
        match event:
            case SessionEvent(state=SessionState.STARTING):
                if event.session_id != self.session_id:
                    self._reset_session(event.session_id)
                self.runtime_state = "starting"
            case SessionEvent(state=SessionState.READY):
                self.runtime_state = "running"
            case SessionEvent(state=SessionState.STOPPING):
                if self.runtime_state != "failed":
                    self.runtime_state = "stopping"
            case SessionEvent(state=SessionState.STOPPED):
                if self.runtime_state != "failed":
                    self.runtime_state = "idle"
                self._discard_active_turn()
                self._clear_activity()
                self.input_level = 0.0
                self.input_gate = None
            case ComponentEvent():
                self.components[event.component.value] = {
                    "state": event.state.value,
                    "elapsed_ms": event.elapsed_ms,
                }
            case InputLevelEvent():
                self.input_level = event.level
                self.input_gate = (
                    {
                        "level_db": event.level_db,
                        "noise_floor_db": event.noise_floor_db,
                        "threshold_db": event.threshold_db,
                        "mode": event.gate_mode,
                        "passed": event.gate_passed,
                    }
                    if event.gate_mode is not None
                    else None
                )
            case SpeechEvent(state=SpeechState.STARTED):
                self._speech_active = True
                self._awaiting_transcript = False
                self.live_transcript = None
            case SpeechEvent(state=SpeechState.STOPPED):
                self._speech_active = False
                self._awaiting_transcript = True
            case TranscriptEvent():
                self.live_transcript = {
                    "text": event.text,
                    "is_final": event.is_final,
                    "language": event.language,
                }
            case UserInputEvent():
                self._awaiting_transcript = False
                self.live_transcript = None
                self._create_turn(event)
            case TurnEvent(state=TurnState.STARTED):
                self._active_turn_id = event.turn_id
                self._turn(event.turn_id)["state"] = event.state.value
            case TurnEvent(
                state=TurnState.COMPLETED | TurnState.INTERRUPTED | TurnState.FAILED
            ):
                self._turn(event.turn_id)["state"] = event.state.value
                self._active_turn_id = None
                self._active_tool_ids.clear()
                self._synthesis_active = False
                self._playback_active = False
            case AgentTextEvent():
                parts = self._turn(event.turn_id)["assistant"]["parts"]
                if not parts or parts[-1]["type"] != "text":
                    parts.append({"type": "text", "text": ""})
                parts[-1]["text"] += event.delta
            case ToolCallStartedEvent():
                self._active_tool_ids.add(event.call_id)
                self._turn(event.turn_id)["assistant"]["parts"].append(
                    {
                        "type": "tool",
                        "call_id": event.call_id,
                        "name": event.name,
                        "arguments": dict(event.arguments),
                        "state": "running",
                        "result": None,
                        "elapsed_ms": None,
                    }
                )
            case ToolCallFinishedEvent():
                tool = self._tool(event.turn_id, event.call_id)
                tool.update(
                    state="succeeded" if event.succeeded else "failed",
                    result=event.result,
                    elapsed_ms=event.elapsed_ms,
                )
                if event.file_changes:
                    tool["file_changes"] = [
                        dict(change) for change in event.file_changes
                    ]
                self._active_tool_ids.discard(event.call_id)
            case SynthesisEvent(state=SynthesisState.STARTED):
                self._synthesis_active = True
            case SynthesisEvent(
                state=(
                    SynthesisState.FINISHED
                    | SynthesisState.INTERRUPTED
                    | SynthesisState.FAILED
                )
            ):
                self._synthesis_active = False
            case PlaybackEvent(state=PlaybackState.STARTED | PlaybackState.PROGRESS):
                self._playback_active = True
                assistant = self._turn(event.turn_id)["assistant"]
                assistant["playback_state"] = event.state.value
                assistant["spoken_text"] = event.spoken_text
            case PlaybackEvent(
                state=(
                    PlaybackState.FINISHED
                    | PlaybackState.INTERRUPTED
                    | PlaybackState.FAILED
                )
            ):
                self._playback_active = False
                assistant = self._turn(event.turn_id)["assistant"]
                assistant["playback_state"] = event.state.value
                assistant["spoken_text"] = event.spoken_text
            case MetricsEvent():
                self._turn(event.turn_id)["metrics"] = asdict(event.metrics)
            case ErrorEvent():
                error = {
                    "component": event.component.value,
                    "operation": event.operation,
                    "message": event.message,
                    "error_type": event.error_type,
                    "fatal": event.fatal,
                }
                if event.turn_id is None:
                    self.error = error
                else:
                    self._turn(event.turn_id)["error"] = error
                if event.fatal:
                    self.runtime_state = "failed"

        self._update_stage(event.timestamp)

    def _create_turn(self, event: UserInputEvent) -> None:
        turn = {
            "session_id": event.session_id,
            "turn_id": event.turn_id,
            "source": event.source.value,
            "user_text": (
                ""
                if event.source in {
                    InputSource.OPENING,
                    InputSource.PROACTIVE,
                    InputSource.FOLLOWUP,
                }
                else event.text
            ),
            "state": "started",
            "assistant": {
                "parts": [],
                "playback_state": None,
                "spoken_text": "",
            },
            "metrics": None,
            "error": None,
        }
        self.turns.append(turn)
        self._turns_by_id[event.turn_id] = turn

    def _turn(self, turn_id: int) -> dict[str, Any]:
        return self._turns_by_id[turn_id]

    def _tool(self, turn_id: int, call_id: str) -> dict[str, Any]:
        for part in self._turn(turn_id)["assistant"]["parts"]:
            if part["type"] == "tool" and part["call_id"] == call_id:
                return part
        raise KeyError(call_id)

    def _reset_session(self, session_id: str) -> None:
        self.session_id = session_id
        self.components.clear()
        self.input_level = 0.0
        self.input_gate = None
        self.live_transcript = None
        self._turns_by_id.clear()
        self.error = None
        self._clear_activity()

    def _clear_activity(self) -> None:
        self._active_turn_id = None
        self._active_tool_ids.clear()
        self._speech_active = False
        self._awaiting_transcript = False
        self._synthesis_active = False
        self._playback_active = False
        self.live_transcript = None

    def _discard_active_turn(self) -> None:
        if self._active_turn_id is None:
            return
        turn = self._turns_by_id.pop(self._active_turn_id)
        self.turns.remove(turn)

    def _update_stage(self, timestamp: float | None = None) -> None:
        if self.runtime_state != "running":
            stage = self.runtime_state
        elif self._speech_active:
            stage = "user_speaking"
        elif self._active_tool_ids:
            stage = "tool_running"
        elif self._playback_active:
            stage = "playing"
        elif self._synthesis_active:
            stage = "synthesizing"
        elif self._active_turn_id is not None:
            stage = "thinking"
        elif self._awaiting_transcript:
            stage = "transcribing"
        else:
            stage = "listening"

        if stage != self.stage:
            self.stage = stage
            self.stage_started_at = timestamp

    def _publish(
        self,
        event_type: str,
        data: dict[str, Any],
        *,
        timestamp: float | None = None,
    ) -> None:
        self.sequence += 1
        message: dict[str, Any] = {
            "seq": self.sequence,
            "type": event_type,
            "stage": self.stage,
            "stage_started_at": self.stage_started_at,
            "data": data,
        }
        if timestamp is not None:
            message["timestamp"] = timestamp
        self._send(message)

    def _send(self, message: dict[str, Any]) -> None:
        queue = self._client_queue
        if queue is None:
            return
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            while not queue.empty():
                queue.get_nowait()
            queue.put_nowait({"type": "stream.overflow"})
            self._client_queue = None
