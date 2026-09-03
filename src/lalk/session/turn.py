"""Run one interruptible Bumblehive response through TTS and audio output."""

import asyncio
import time
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import bumblehive
from bumblehive.agent import AgentRunResult
from bumblehive.observability import (
    MODEL_REQUEST_STARTED,
    MODEL_RESPONSE_FINISHED,
    MODEL_STREAM_CONTENT_DELTA,
    MODEL_STREAM_REFUSAL_DELTA,
    TOOL_CALL_FINISHED,
    TOOL_CALL_STARTED,
    TOOL_CALLS_FINISHED,
    TOOL_CALLS_STARTED,
    AgentEvent,
)

from ..agent import AgentTurn, BumblehiveAgent
from ..asr import ASRResult
from ..audio import AudioChunk, AudioError, AudioIO
from ..observability import (
    AgentRequestEvent,
    AgentTextEvent,
    Component,
    PlaybackEvent,
    PlaybackState,
    SynthesisEvent,
    SynthesisState,
    ToolCallFinishedEvent,
    ToolCallStartedEvent,
    TurnMetrics,
    VoiceEvent,
)
from ..observability._turn_tracker import _TurnMetricsTracker
from ..tts import (
    TTS,
    StreamingTextProcessor,
    TTSResult,
    TTSStream,
    TTSTextMark,
)

_TEXT_EVENTS = (MODEL_STREAM_CONTENT_DELTA, MODEL_STREAM_REFUSAL_DELTA)
_PLAYBACK_PROGRESS_INTERVAL_SECONDS = 0.05
_TOOL_COMPLETION_GRACE_SECONDS = 2.0
_Message = dict[str, Any]


@dataclass(frozen=True, slots=True)
class _TurnOutcome:
    interrupted: bool
    messages: list[_Message]
    failure: "_TurnFailure | None" = None


class _TurnFailure(Exception):
    """Failure classified at the component boundary of one turn."""

    def __init__(
        self,
        *,
        component: Component,
        operation: str,
        error: Exception,
        fatal: bool,
    ) -> None:
        super().__init__(str(error))
        self.component = component
        self.operation = operation
        self.error = error
        self.fatal = fatal


@dataclass(frozen=True, slots=True)
class _TextDelta:
    response_index: int
    text: str


@dataclass(frozen=True, slots=True)
class _ResponseEnd:
    response_index: int


@dataclass(frozen=True, slots=True)
class _ResponsePlayback:
    text: str


_TTSInputItem = _TextDelta | _ResponseEnd | None
_PlaybackItem = AudioChunk | None


class _PlaybackTracker:
    """Map TTS text marks onto output progress for one synthesis stream."""

    def __init__(self, audio: AudioIO) -> None:
        self._audio = audio
        self._start_frame = audio.played_frames
        self._marks: list[TTSTextMark] = []
        self._submitted: dict[int, str] = {}

    def submit(self, response_index: int, text: str) -> None:
        self._submitted[response_index] = self._submitted.get(response_index, "") + text

    def mark(self, mark: TTSTextMark) -> None:
        self._marks.append(mark)

    @property
    def spoken_text(self) -> str:
        """Return text confirmed by provider marks and output progress."""

        return self._spoken_text()

    @property
    def submitted_text(self) -> str:
        """Return all text submitted to synthesis in response order."""

        return "".join(self._submitted.values())

    @property
    def played_frames(self) -> int:
        """Output frames confirmed as played during this turn."""

        return max(self._audio.played_frames - self._start_frame, 0)

    def response_playback(self, count: int) -> list[_ResponsePlayback]:
        remaining = self._spoken_text()
        responses: list[_ResponsePlayback] = []
        for index in range(count):
            submitted = self._submitted.get(index, "")
            heard = remaining[: len(submitted)]
            remaining = remaining[len(heard) :]
            responses.append(_ResponsePlayback(text=heard))
        return responses

    def _spoken_text(self) -> str:
        played = self.played_frames
        if played <= 0:
            return ""
        return "".join(mark.text for mark in self._marks if mark.at_frame <= played)


class _TurnJournal:
    """Project partial Bumblehive events into valid interrupted history."""

    def __init__(self, prompt: str) -> None:
        self._messages: list[_Message] = [{"role": "user", "content": prompt}]
        self._draft_text = ""
        self._response_index = 0
        self._started_tool_ids: set[str] = set()
        self._active_tool_ids: set[str] = set()
        self._tools_finished = asyncio.Event()
        self._tools_finished.set()

    @property
    def response_index(self) -> int:
        return self._response_index

    @property
    def response_count(self) -> int:
        count = sum(message.get("role") == "assistant" for message in self._messages)
        return count + bool(self._draft_text)

    @property
    def tools_active(self) -> bool:
        return bool(self._active_tool_ids)

    @property
    def latest_assistant_has_text(self) -> bool:
        for message in reversed(self._messages):
            if message.get("role") != "assistant":
                continue
            content = message.get("content")
            return isinstance(content, str) and bool(content.strip())
        return False

    async def wait_until_tools_finish(self) -> None:
        await self._tools_finished.wait()

    def record(self, event: AgentEvent) -> None:
        if event.kind in _TEXT_EVENTS:
            delta = event.payload.get("delta")
            if isinstance(delta, str):
                self._draft_text += delta
            return

        if event.kind == MODEL_RESPONSE_FINISHED:
            message = event.payload.get("message")
            if isinstance(message, Mapping):
                self._messages.append(dict(message))
            else:
                self._messages.append(
                    {"role": "assistant", "content": self._draft_text}
                )
            self._draft_text = ""
            self._response_index += 1
            return

        if event.kind == TOOL_CALLS_STARTED:
            tool_ids = self._latest_tool_call_ids()
            self._started_tool_ids.update(tool_ids)
            self._active_tool_ids = set(tool_ids)
            if tool_ids:
                self._tools_finished.clear()
            return

        if event.kind == TOOL_CALL_FINISHED:
            message = event.payload.get("tool_result")
            if isinstance(message, Mapping):
                self._messages.append(dict(message))
            return

        if event.kind == TOOL_CALLS_FINISHED:
            self._active_tool_ids.clear()
            self._tools_finished.set()

    def interrupted_messages(
        self,
        playback: list[_ResponsePlayback],
    ) -> list[_Message]:
        messages = [dict(message) for message in self._messages]
        if self._draft_text:
            messages.append({"role": "assistant", "content": self._draft_text})

        tool_results = _tool_results(messages)
        interrupted: list[_Message] = []
        response_index = 0

        for message in messages:
            role = message.get("role")
            if role == "tool":
                continue
            if role != "assistant":
                interrupted.append(message)
                continue

            heard = (
                playback[response_index]
                if response_index < len(playback)
                else _ResponsePlayback("")
            )
            response_index += 1
            tool_ids = _tool_call_ids(message)

            if tool_ids:
                executed = set(tool_ids) <= self._started_tool_ids and all(
                    tool_id in tool_results for tool_id in tool_ids
                )
                if executed:
                    assistant = dict(message)
                    assistant["content"] = heard.text or None
                    interrupted.append(assistant)
                    interrupted.extend(tool_results[tool_id] for tool_id in tool_ids)
                elif heard.text:
                    interrupted.append({"role": "assistant", "content": heard.text})
                continue

            if heard.text:
                interrupted.append({"role": "assistant", "content": heard.text})

        return interrupted

    def _latest_tool_call_ids(self) -> list[str]:
        for message in reversed(self._messages):
            if message.get("role") == "assistant":
                return _tool_call_ids(message)
        return []


class _TurnRunner:
    """Coordinate one agent turn without committing conversation history."""

    def __init__(
        self,
        *,
        prompt: str,
        history: bumblehive.MessageHistory,
        audio: AudioIO,
        agent: BumblehiveAgent,
        tts: TTS,
        session_id: str,
        turn_id: int,
        emit: Callable[[VoiceEvent], None],
        prompt_ready_at: float,
        speech_stopped_at: float | None = None,
        estimated_speech_ended_at: float | None = None,
        turn_decided_at: float | None = None,
        asr_finished_at: float | None = None,
        asr_result: ASRResult | None = None,
    ) -> None:
        self._prompt = prompt
        self._history = history
        self._audio = audio
        self._agent = agent
        self._tts = tts
        self._session_id = session_id
        self._turn_id = turn_id
        self._emit = emit
        self._metrics = _TurnMetricsTracker(
            prompt_ready_at=prompt_ready_at,
            speech_stopped_at=speech_stopped_at,
            estimated_speech_ended_at=estimated_speech_ended_at,
            turn_decided_at=turn_decided_at,
            asr_finished_at=asr_finished_at,
            asr_result=asr_result,
        )

        self._journal = _TurnJournal(prompt)
        self._playback = _PlaybackTracker(audio)
        # Agent events must keep flowing while playback is slower so tool state
        # remains available to interruption cleanup.
        self._tts_input: asyncio.Queue[_TTSInputItem] = asyncio.Queue()
        # Provider marks can arrive behind audio, so device backpressure must not
        # stop the TTS stream from reaching them.
        self._playback_items: asyncio.Queue[_PlaybackItem] = asyncio.Queue()
        self._interruption = asyncio.Event()
        self._tts_stopped = asyncio.Event()

        self._turn: AgentTurn | None = None
        self._tts_stream: TTSStream | None = None
        self._agent_task: asyncio.Task[AgentRunResult] | None = None
        self._tts_task: asyncio.Task[None] | None = None
        self._playback_task: asyncio.Task[None] | None = None
        self._playback_progress_task: asyncio.Task[None] | None = None

        self._synthesis_started_at: float | None = None
        self._synthesis_terminal = False
        self._received_first_audio = False
        self._playback_started = False
        self._playback_active = False
        self._last_spoken_text = ""
        self._suppress_after_end_tool = False

    @property
    def playback_active(self) -> bool:
        """Whether assistant audio has started and not reached a terminal state."""

        return self._playback_active

    def interrupt(self) -> bool:
        """Request interruption without blocking microphone capture."""

        if self._interruption.is_set():
            return False
        self._metrics.mark_interruption_requested()
        self._interruption.set()
        return True

    def failure_messages(self) -> list[_Message]:
        """Return valid history after a failed partial response."""

        playback = self._playback.response_playback(self._journal.response_count)
        return self._journal.interrupted_messages(playback)

    def metrics(self) -> TurnMetrics:
        """Build a final timing and usage snapshot for this turn."""

        return self._metrics.snapshot()

    async def run(self) -> _TurnOutcome:
        try:
            self._turn = self._agent.stream(self._prompt, history=self._history)
        except Exception as error:
            raise _TurnFailure(
                component=Component.AGENT,
                operation="stream",
                error=error,
                fatal=False,
            ) from error

        try:
            self._tts_stream = self._tts.synthesize(self._stream_tts_text())
        except Exception as error:
            await asyncio.gather(self._turn.aclose(), return_exceptions=True)
            raise _TurnFailure(
                component=Component.TTS,
                operation="synthesize",
                error=error,
                fatal=False,
            ) from error

        self._agent_task = asyncio.create_task(
            self._consume_agent(),
            name="lalk-agent-turn",
        )
        self._playback_task = asyncio.create_task(
            self._play_audio(),
            name="lalk-audio-playback",
        )
        self._tts_task = asyncio.create_task(
            self._consume_tts(),
            name="lalk-tts-stream",
        )
        completion = asyncio.create_task(
            self._complete(),
            name="lalk-turn-completion",
        )
        interruption = asyncio.create_task(
            self._interruption.wait(),
            name="lalk-turn-interruption",
        )
        outcome_ready = False

        try:
            done, _ = await asyncio.wait(
                {completion, interruption},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if completion in done:
                result = await completion
                if result.usage:
                    self._metrics.set_llm_usage(result.usage)
                failure = None
                if result.error is not None:
                    failure = _TurnFailure(
                        component=Component.AGENT,
                        operation="run",
                        error=RuntimeError(
                            f"{result.error.code}: {result.error.message}"
                        ),
                        fatal=not result.error.recoverable,
                    )
                outcome = _TurnOutcome(
                    interrupted=False,
                    messages=[dict(message) for message in result.messages],
                    failure=failure,
                )
            else:
                outcome = await self._interrupt_turn()

            outcome_ready = True
            return outcome
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            try:
                await self._fail_playback()
            except BaseException as playback_error:
                raise playback_error from error
            raise
        finally:
            interruption.cancel()
            await asyncio.gather(interruption, return_exceptions=True)
            if not completion.done():
                completion.cancel()
            await asyncio.gather(completion, return_exceptions=True)
            await self._close(suppress_errors=not outcome_ready)

    async def _consume_agent(self) -> AgentRunResult:
        turn = self._require_turn()
        try:
            async for event in turn:
                if event.kind == TOOL_CALL_STARTED:
                    call = event.payload.get("tool_call")
                    if (
                        isinstance(call, Mapping)
                        and call.get("name") == "end_voice_session"
                    ):
                        self._suppress_after_end_tool = (
                            self._journal.latest_assistant_has_text
                        )

                if event.kind in _TEXT_EVENTS and self._suppress_after_end_tool:
                    self._journal.record(event)
                    continue

                self._observe_agent_event(event)
                response_index = self._journal.response_index
                self._journal.record(event)
                if self._tts_stopped.is_set():
                    continue

                if event.kind in _TEXT_EVENTS:
                    delta = event.payload.get("delta")
                    if isinstance(delta, str) and delta:
                        self._tts_input.put_nowait(_TextDelta(response_index, delta))
                elif event.kind == MODEL_RESPONSE_FINISHED:
                    self._tts_input.put_nowait(_ResponseEnd(response_index))
            return await turn.result()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise _TurnFailure(
                component=Component.AGENT,
                operation="stream",
                error=error,
                fatal=False,
            ) from error
        finally:
            self._tts_input.put_nowait(None)

    async def _consume_tts(self) -> None:
        tts_stream = self._require_tts_stream()
        try:
            async for output in tts_stream:
                if isinstance(output, TTSTextMark):
                    self._playback.mark(output)
                    self._emit_playback_progress()
                    continue
                if not isinstance(output, AudioChunk):
                    raise TypeError(f"Unsupported TTS output: {type(output).__name__}")
                if self._interruption.is_set():
                    continue
                self._metrics.mark_tts_audio()
                if not self._received_first_audio:
                    self._received_first_audio = True
                    self._emit_synthesis(SynthesisState.FIRST_AUDIO)
                self._playback_items.put_nowait(output)

            result = await tts_stream.result()
            self._record_tts_result(result)
            if not result.completed:
                raise RuntimeError("TTS synthesis did not complete")
            self._finish_synthesis(SynthesisState.FINISHED)
            self._playback_items.put_nowait(None)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._finish_synthesis(SynthesisState.FAILED)
            raise _TurnFailure(
                component=Component.TTS,
                operation="synthesize",
                error=error,
                fatal=False,
            ) from error

    async def _play_audio(self) -> None:
        try:
            while True:
                item = await self._playback_items.get()
                if item is None:
                    break
                if self._interruption.is_set():
                    continue
                if not self._playback_started:
                    self._playback_started = True
                    self._playback_active = True
                    self._emit(
                        PlaybackEvent(
                            session_id=self._session_id,
                            turn_id=self._turn_id,
                            state=PlaybackState.STARTED,
                        )
                    )
                    self._start_playback_progress()
                await self._audio.write(item)
                self._emit_playback_progress()

            await self._audio.wait_for_playback()
            await self._stop_playback_progress()
            self._emit_playback_progress()
            self._emit_playback_terminal(
                PlaybackState.FINISHED,
                self._playback.submitted_text,
            )
        except asyncio.CancelledError:
            raise
        except AudioError:
            raise
        except Exception as error:
            raise AudioError(f"Audio playback failed: {error}") from error

    async def _stream_tts_text(self) -> AsyncIterator[str]:
        processor = StreamingTextProcessor()
        response_index = 0

        def ready_parts(
            text: str,
            index: int,
            *,
            finish: bool = False,
        ) -> list[str]:
            parts = processor.push(text) if text else []
            if finish:
                parts.extend(processor.flush())
            for part in parts:
                self._record_first_tts_text()
                self._playback.submit(index, part)
            return parts

        while True:
            item = await self._tts_input.get()
            if item is None:
                for text in ready_parts(
                    "",
                    response_index,
                    finish=True,
                ):
                    yield text
                return

            if isinstance(item, _TextDelta):
                response_index = item.response_index
                for text in ready_parts(item.text, response_index):
                    yield text
                continue

            if isinstance(item, _ResponseEnd):
                for text in ready_parts(
                    "",
                    item.response_index,
                    finish=True,
                ):
                    yield text
                response_index = item.response_index + 1

    async def _complete(self) -> AgentRunResult:
        agent_task = self._require_agent_task()
        tts_task = self._require_tts_task()
        playback_task = self._require_playback_task()
        await asyncio.gather(agent_task, tts_task, playback_task)
        return agent_task.result()

    async def _interrupt_turn(self) -> _TurnOutcome:
        self._tts_stopped.set()
        await self._audio.interrupt_playback()
        await self._stop_playback_progress()
        self._metrics.mark_interruption_finished()
        self._emit_playback_terminal(
            PlaybackState.INTERRUPTED,
            self._playback.spoken_text,
        )
        await self._stop_output()
        self._finish_synthesis(SynthesisState.INTERRUPTED)

        agent_task = self._require_agent_task()
        if self._journal.tools_active and not agent_task.done():
            tools_finished = asyncio.create_task(
                self._journal.wait_until_tools_finish(),
                name="lalk-tools-finished",
            )
            try:
                await asyncio.wait(
                    {agent_task, tools_finished},
                    timeout=_TOOL_COMPLETION_GRACE_SECONDS,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                tools_finished.cancel()
                await asyncio.gather(tools_finished, return_exceptions=True)

        if not agent_task.done():
            agent_task.cancel()
        await asyncio.gather(agent_task, return_exceptions=True)

        playback = self._playback.response_playback(self._journal.response_count)
        return _TurnOutcome(
            interrupted=True,
            messages=self._journal.interrupted_messages(playback),
        )

    async def _stop_output(self) -> None:
        tts_task = self._require_tts_task()
        playback_task = self._require_playback_task()
        for task in (tts_task, playback_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(tts_task, playback_task, return_exceptions=True)
        tts_stream = self._require_tts_stream()
        await tts_stream.aclose()
        self._record_tts_result(await tts_stream.result())

    async def _fail_playback(self) -> None:
        if not self._playback_started:
            return
        await self._audio.interrupt_playback()
        await self._stop_playback_progress()
        self._emit_playback_terminal(
            PlaybackState.FAILED,
            self._playback.spoken_text,
        )

    def _observe_agent_event(self, event: AgentEvent) -> None:
        if event.kind == MODEL_REQUEST_STARTED:
            self._metrics.mark_model_request_started()
            request = event.payload.get("request")
            if isinstance(request, Mapping):
                messages = request.get("messages")
                if isinstance(messages, list) and all(
                    isinstance(message, Mapping) for message in messages
                ):
                    self._emit(
                        AgentRequestEvent(
                            session_id=self._session_id,
                            turn_id=self._turn_id,
                            messages=tuple(dict(message) for message in messages),
                        )
                    )

        if event.kind in _TEXT_EVENTS:
            delta = event.payload.get("delta")
            if isinstance(delta, str) and delta:
                self._metrics.mark_agent_text()
                self._emit(
                    AgentTextEvent(
                        session_id=self._session_id,
                        turn_id=self._turn_id,
                        delta=delta,
                    )
                )
            return

        if event.kind == MODEL_RESPONSE_FINISHED:
            usage = event.payload.get("usage")
            if isinstance(usage, Mapping):
                self._metrics.add_llm_usage(usage)
            return

        if event.kind == TOOL_CALL_STARTED:
            call = event.payload["tool_call"]
            self._emit(
                ToolCallStartedEvent(
                    session_id=self._session_id,
                    turn_id=self._turn_id,
                    call_id=call["call_id"],
                    name=call["name"],
                    arguments=dict(call["arguments"]),
                )
            )
            return

        if event.kind == TOOL_CALL_FINISHED:
            result = event.payload["tool_result"]
            raw_file_changes = event.payload.get("file_changes")
            file_changes = (
                tuple(
                    dict(change)
                    for change in raw_file_changes
                    if isinstance(change, Mapping)
                )
                if isinstance(raw_file_changes, list)
                else ()
            )
            self._emit(
                ToolCallFinishedEvent(
                    session_id=self._session_id,
                    turn_id=self._turn_id,
                    call_id=result["tool_call_id"],
                    name=result["name"],
                    result=result["content"],
                    succeeded=event.payload["ok"],
                    elapsed_ms=round(event.payload["duration_s"] * 1_000, 1),
                    file_changes=file_changes,
                )
            )

    def _record_first_tts_text(self) -> None:
        self._metrics.mark_tts_text()
        if self._synthesis_started_at is None:
            self._synthesis_started_at = time.perf_counter()
            self._emit_synthesis(SynthesisState.STARTED)

    def _emit_synthesis(self, state: SynthesisState) -> None:
        started_at = self._synthesis_started_at
        if started_at is None:
            return
        self._emit(
            SynthesisEvent(
                session_id=self._session_id,
                turn_id=self._turn_id,
                state=state,
                elapsed_ms=(
                    0.0
                    if state is SynthesisState.STARTED
                    else _duration_ms(started_at, time.perf_counter())
                ),
            )
        )

    def _finish_synthesis(self, state: SynthesisState) -> None:
        if self._synthesis_started_at is None or self._synthesis_terminal:
            return
        self._synthesis_terminal = True
        self._emit_synthesis(state)

    def _record_tts_result(self, result: TTSResult) -> None:
        self._metrics.set_tts_usage(
            provider_usage=result.provider_usage,
            input_characters=result.input_characters,
            audio_bytes=result.audio_bytes,
        )

    def _start_playback_progress(self) -> None:
        if self._playback_progress_task is None:
            self._playback_progress_task = asyncio.create_task(
                self._monitor_playback_progress(),
                name="lalk-playback-progress",
            )

    async def _monitor_playback_progress(self) -> None:
        while True:
            self._emit_playback_progress()
            await asyncio.sleep(_PLAYBACK_PROGRESS_INTERVAL_SECONDS)

    async def _stop_playback_progress(self) -> None:
        task = self._playback_progress_task
        if task is None:
            return
        self._playback_progress_task = None
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    def _emit_playback_progress(self) -> None:
        self._record_first_playback()
        spoken = self._playback.spoken_text
        if (
            not spoken.startswith(self._last_spoken_text)
            or spoken == self._last_spoken_text
        ):
            return
        delta = spoken[len(self._last_spoken_text) :]
        self._last_spoken_text = spoken
        self._emit(
            PlaybackEvent(
                session_id=self._session_id,
                turn_id=self._turn_id,
                state=PlaybackState.PROGRESS,
                spoken_text=spoken,
                delta=delta,
            )
        )

    def _emit_playback_terminal(self, state: PlaybackState, spoken: str) -> None:
        self._playback_active = False
        self._record_first_playback()
        delta = ""
        if spoken.startswith(self._last_spoken_text):
            delta = spoken[len(self._last_spoken_text) :]
        self._last_spoken_text = spoken
        self._emit(
            PlaybackEvent(
                session_id=self._session_id,
                turn_id=self._turn_id,
                state=state,
                spoken_text=spoken,
                delta=delta,
            )
        )

    def _record_first_playback(self) -> None:
        if self._playback.played_frames > 0:
            self._metrics.mark_playback()

    async def _close(self, *, suppress_errors: bool) -> None:
        errors: list[Exception] = []
        tasks: list[asyncio.Task[Any]] = []
        await self._stop_playback_progress()
        for task in (self._tts_task, self._playback_task, self._agent_task):
            if task is not None:
                tasks.append(task)
                if not task.done():
                    task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        for stream in (self._tts_stream, self._turn):
            if stream is None:
                continue
            try:
                await stream.aclose()
            except Exception as error:  # noqa: BLE001 - both streams must close
                errors.append(error)

        self._finish_synthesis(SynthesisState.INTERRUPTED)
        if errors and not suppress_errors:
            raise errors[0]

    def _require_turn(self) -> AgentTurn:
        if self._turn is None:
            raise RuntimeError("Agent turn has not started")
        return self._turn

    def _require_tts_stream(self) -> TTSStream:
        if self._tts_stream is None:
            raise RuntimeError("TTS stream has not started")
        return self._tts_stream

    def _require_agent_task(self) -> asyncio.Task[AgentRunResult]:
        if self._agent_task is None:
            raise RuntimeError("Agent task has not started")
        return self._agent_task

    def _require_tts_task(self) -> asyncio.Task[None]:
        if self._tts_task is None:
            raise RuntimeError("TTS task has not started")
        return self._tts_task

    def _require_playback_task(self) -> asyncio.Task[None]:
        if self._playback_task is None:
            raise RuntimeError("Playback task has not started")
        return self._playback_task


def _tool_results(messages: list[_Message]) -> dict[str, _Message]:
    return {
        message["tool_call_id"]: dict(message)
        for message in messages
        if message.get("role") == "tool"
        and isinstance(message.get("tool_call_id"), str)
    }


def _tool_call_ids(message: Mapping[str, Any]) -> list[str]:
    calls = message.get("tool_calls")
    if not isinstance(calls, list):
        return []

    identifiers: list[str] = []
    for call in calls:
        if not isinstance(call, Mapping):
            continue
        identifier = call.get("id")
        if isinstance(identifier, str) and identifier:
            identifiers.append(identifier)
    return identifiers


def _duration_ms(start: float, end: float) -> float:
    return round(max(end - start, 0) * 1_000, 1)
