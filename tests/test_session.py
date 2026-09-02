import asyncio
from collections import deque
from collections.abc import AsyncIterable, AsyncIterator, Collection
from typing import Any, Self, cast

import bumblehive
import pytest
from bumblehive.agent import AgentRunResult
from bumblehive.observability import (
    MODEL_REQUEST_STARTED,
    MODEL_RESPONSE_FINISHED,
    MODEL_STREAM_CONTENT_DELTA,
    TOOL_CALL_FINISHED,
    TOOL_CALL_STARTED,
    TOOL_CALLS_FINISHED,
    TOOL_CALLS_STARTED,
    AgentEvent,
)

import lalk.session.turn as turn_module
from lalk import (
    ConversationInactivityPolicy,
    InactivityAction,
    VoiceSession,
)
from lalk.agent import BumblehiveAgent
from lalk.asr import ASRResult, Transcript
from lalk.audio import AudioChunk, AudioFormat, AudioFormatError
from lalk.observability import (
    AgentRequestEvent,
    AgentTextEvent,
    Component,
    ComponentEvent,
    ComponentState,
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
from lalk.session._voice_input import (
    _collect_transcripts,
    _normalize_speech_content,
    _StreamingRecognition,
)
from lalk.tts import TTSOutput, TTSResult, TTSTextMark
from lalk.turn_detection import TurnAnalysis
from lalk.vad import AdaptiveInputLevelGate, VADState

pytestmark = pytest.mark.asyncio

_INPUT_FORMAT = AudioFormat(16_000)
_OUTPUT_FORMAT = AudioFormat(48_000)
_CAPTURE_END = object()
_ASR_END = object()


def _chunk(value: int, *, output: bool = False) -> AudioChunk:
    audio_format = _OUTPUT_FORMAT if output else _INPUT_FORMAT
    return AudioChunk(value.to_bytes(2, "little", signed=True) * 320, audio_format)


class _FakeAudio:
    def __init__(self, log: list[str]) -> None:
        self.input_format = _INPUT_FORMAT
        self.output_format = _OUTPUT_FORMAT
        self.log = log
        self.items: asyncio.Queue[AudioChunk | BaseException | object] = asyncio.Queue()
        self.started = asyncio.Event()
        self.captured = 0
        self.writes: list[AudioChunk] = []
        self.write_started = asyncio.Event()
        self.write_allowed = asyncio.Event()
        self.write_allowed.set()
        self.played_frames = 0
        self.play_immediately = True
        self.playback_finished = asyncio.Event()
        self.playback_finished.set()
        self.interrupt_calls = 0
        self.interrupted = asyncio.Event()

    async def start(self) -> None:
        self.log.append("audio.start")
        self.started.set()

    async def capture(self) -> AsyncIterator[AudioChunk]:
        while True:
            item = await self.items.get()
            if item is _CAPTURE_END:
                return
            if isinstance(item, BaseException):
                raise item
            if isinstance(item, AudioChunk):
                self.captured += 1
                yield item

    async def write(self, chunk: AudioChunk) -> None:
        self.write_started.set()
        await self.write_allowed.wait()
        self.writes.append(chunk)
        if self.play_immediately:
            self.played_frames += chunk.frame_count

    async def wait_for_playback(self) -> None:
        await self.playback_finished.wait()

    async def interrupt_playback(self) -> None:
        self.interrupt_calls += 1
        self.interrupted.set()

    async def close(self) -> None:
        self.log.append("audio.close")

    def emit(self, item: AudioChunk | BaseException | object) -> None:
        self.items.put_nowait(item)

    def queue_playback(self) -> None:
        self.play_immediately = False
        self.playback_finished.clear()

    def advance_playback(self, frames: int) -> None:
        self.played_frames += frames

    def finish_playback(self) -> None:
        self.playback_finished.set()


class _FakeVAD:
    def __init__(self, log: list[str]) -> None:
        self.speech_start_confirmation_seconds = 0.2
        self.speech_end_confirmation_seconds = 0.2
        self.log = log
        self.states: deque[VADState] = deque()
        self.analyzed = 0
        self.chunks: list[AudioChunk] = []

    async def start(self, input_format: AudioFormat) -> None:
        assert input_format == _INPUT_FORMAT
        self.log.append("vad.start")

    async def analyze(self, chunk: AudioChunk) -> VADState:
        self.chunks.append(chunk)
        self.analyzed += 1
        return self.states.popleft() if self.states else VADState.SILENCE

    async def close(self) -> None:
        self.log.append("vad.close")


class _FakeASRStream:
    def __init__(self, owner: "_FakeASR") -> None:
        self._owner = owner
        self._audio = bytearray()
        self._outputs: asyncio.Queue[Transcript | object] = asyncio.Queue()
        self._done = asyncio.Event()
        self._closed = False
        self._result = ASRResult(0.0, 0, False)

    def __aiter__(self) -> Self:
        return self

    @property
    def closed(self) -> bool:
        return self._closed

    async def __anext__(self) -> Transcript:
        if self._closed:
            raise StopAsyncIteration
        item = await self._outputs.get()
        if item is _ASR_END:
            raise StopAsyncIteration
        assert isinstance(item, Transcript)
        return item

    def emit(self, transcript: Transcript) -> None:
        self._outputs.put_nowait(transcript)

    async def write(self, audio: AudioChunk) -> None:
        if self._owner.fail_write:
            raise RuntimeError("asr write failed")
        self._audio.extend(audio.data)

    async def finish(self) -> None:
        audio = AudioChunk(bytes(self._audio), _INPUT_FORMAT)
        self._owner.calls.append(audio)
        await self._owner.transcription_allowed.wait()
        transcript = self._owner.transcripts.popleft()
        self._result = ASRResult(
            input_audio_seconds=audio.duration_seconds,
            output_characters=len(transcript.text),
            completed=True,
        )
        self._outputs.put_nowait(transcript)
        self._outputs.put_nowait(_ASR_END)
        self._done.set()
        self._owner.transcribed.set()

    async def result(self) -> ASRResult:
        await self._done.wait()
        return self._result

    async def aclose(self) -> None:
        self._closed = True
        self._outputs.put_nowait(_ASR_END)
        self._done.set()


class _FakeASR:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.transcripts: deque[Transcript] = deque()
        self.calls: list[AudioChunk] = []
        self.streams: list[_FakeASRStream] = []
        self.transcribed = asyncio.Event()
        self.transcription_allowed = asyncio.Event()
        self.transcription_allowed.set()
        self.fail_write = False
        self.supports_interim_transcripts = False

    async def start(self, input_format: AudioFormat) -> None:
        assert input_format == _INPUT_FORMAT
        self.log.append("asr.start")

    def recognize(self) -> _FakeASRStream:
        stream = _FakeASRStream(self)
        self.streams.append(stream)
        return stream

    async def close(self) -> None:
        self.log.append("asr.close")


class _FakeTurnAnalyzer:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.results: deque[TurnAnalysis] = deque()
        self.calls: list[AudioChunk] = []
        self.analysis_started = asyncio.Event()
        self.analysis_allowed = asyncio.Event()
        self.analysis_allowed.set()

    async def start(self, input_format: AudioFormat) -> None:
        assert input_format == _INPUT_FORMAT
        self.log.append("turn_detection.start")

    async def analyze(self, audio: AudioChunk) -> TurnAnalysis:
        self.calls.append(audio)
        self.analysis_started.set()
        await self.analysis_allowed.wait()
        if self.results:
            return self.results.popleft()
        return TurnAnalysis(complete=True, probability=0.9)

    async def close(self) -> None:
        self.log.append("turn_detection.close")


class _FakeTurn:
    def __init__(
        self,
        events: list[AgentEvent | asyncio.Event],
        result: AgentRunResult,
        result_returned: asyncio.Event,
    ) -> None:
        self.events = events
        self.result_value = result
        self.result_returned = result_returned
        self.exhausted = False
        self.closed = False
        self.waiting = asyncio.Event()

    def __aiter__(self) -> AsyncIterator[AgentEvent]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[AgentEvent]:
        for event in self.events:
            if isinstance(event, asyncio.Event):
                self.waiting.set()
                await event.wait()
                continue
            yield event
        self.exhausted = True

    async def result(self) -> AgentRunResult:
        assert self.exhausted
        self.result_returned.set()
        return self.result_value

    async def aclose(self) -> None:
        self.closed = True


class _FakeAgent:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.fail_start = False
        self.prompts: list[str] = []
        self.histories: list[list[dict[str, Any]]] = []
        self.turns: list[_FakeTurn] = []
        self.result_returned = asyncio.Event()
        self.next_events: list[AgentEvent | asyncio.Event] | None = None
        self.next_messages: list[dict[str, Any]] | None = None

    async def start(self) -> None:
        self.log.append("agent.start")
        if self.fail_start:
            raise RuntimeError("agent start failed")

    def stream(
        self,
        prompt: str,
        *,
        history: bumblehive.MessageHistory | None = None,
    ) -> _FakeTurn:
        previous = history.get_history() if history is not None else []
        self.prompts.append(prompt)
        self.histories.append(previous)
        answer = "你好！世界"
        messages = [
            *previous,
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": answer},
        ]
        events: list[AgentEvent | asyncio.Event] | None = self.next_events
        if events is None:
            events = [
                AgentEvent(
                    kind=MODEL_STREAM_CONTENT_DELTA,
                    run_id="run-1",
                    payload={"delta": "你好"},
                ),
                AgentEvent(
                    kind=MODEL_STREAM_CONTENT_DELTA,
                    run_id="run-1",
                    payload={"delta": "！世界"},
                ),
            ]
        self.next_events = None
        if self.next_messages is not None:
            messages = [*previous, *self.next_messages]
            self.next_messages = None
        turn = _FakeTurn(
            events,
            AgentRunResult(final_content=answer, messages=messages),
            self.result_returned,
        )
        self.turns.append(turn)
        return turn

    async def close(self) -> None:
        self.log.append("agent.close")


class _FakeTTSStream:
    def __init__(
        self,
        text: AsyncIterable[str],
        owner: "_FakeTTS",
    ) -> None:
        self._owner = owner
        self._iterator = text.__aiter__()
        self._pending: list[TTSOutput] = []
        self._completed = False
        self._audio_bytes = 0
        self._output_frames = 0
        self.closed = False

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> TTSOutput:
        if self.closed:
            raise StopAsyncIteration
        if self._pending:
            output = self._pending.pop(0)
            if isinstance(output, TTSTextMark):
                self._owner.text_marked.set()
                if (
                    self._owner.pause_after_parts is not None
                    and len(self._owner.parts) >= self._owner.pause_after_parts
                ):
                    self._owner.release_audio.clear()
            return output

        try:
            part = await anext(self._iterator)
        except StopAsyncIteration:
            self._completed = True
            raise

        self._owner.parts.append(part)
        self._owner.synthesis_started.set()
        if self._owner.fail_synthesis:
            raise RuntimeError("tts failed")

        await self._owner.release_audio.wait()
        chunk = _chunk(7, output=True)
        self._audio_bytes += len(chunk.data)
        self._output_frames += chunk.frame_count
        if self._owner.emit_text_marks:
            self._pending.append(TTSTextMark(part, self._output_frames))
        return chunk

    async def result(self) -> TTSResult:
        return TTSResult(
            input_characters=sum(map(len, self._owner.parts)),
            audio_bytes=self._audio_bytes,
            completed=self._completed,
        )

    async def aclose(self) -> None:
        self.closed = True


class _FakeTTS:
    output_format = _OUTPUT_FORMAT

    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.parts: list[str] = []
        self.streams: list[_FakeTTSStream] = []
        self.synthesis_started = asyncio.Event()
        self.text_marked = asyncio.Event()
        self.release_audio = asyncio.Event()
        self.release_audio.set()
        self.pause_after_parts: int | None = None
        self.fail_synthesis = False
        self.emit_text_marks = True

    async def start(self) -> None:
        self.log.append("tts.start")

    def synthesize(self, text: str | AsyncIterable[str]) -> _FakeTTSStream:
        assert not isinstance(text, str)
        stream = _FakeTTSStream(text, self)
        self.streams.append(stream)
        return stream

    async def close(self) -> None:
        self.log.append("tts.close")


class _EventCollector:
    def __init__(self, events: list[VoiceEvent]) -> None:
        self._events = events

    def on_event(self, event: VoiceEvent) -> None:
        self._events.append(event)


def _session(
    events: list[VoiceEvent] | None = None,
    *,
    opening_enabled: bool = False,
    inactivity_policy: ConversationInactivityPolicy | None = None,
    input_level_gate: AdaptiveInputLevelGate | None = None,
    turn_analyzer: _FakeTurnAnalyzer | None = None,
    incomplete_turn_timeout_seconds: float = 3.0,
    backchannel_filter_enabled: bool = True,
    backchannel_phrases: Collection[str] | None = None,
) -> tuple[
    VoiceSession,
    _FakeAudio,
    _FakeVAD,
    _FakeASR,
    _FakeAgent,
    _FakeTTS,
    list[str],
]:
    log: list[str] = []
    audio = _FakeAudio(log)
    vad = _FakeVAD(log)
    turn_analyzer = turn_analyzer or _FakeTurnAnalyzer(log)
    asr = _FakeASR(log)
    agent = _FakeAgent(log)
    tts = _FakeTTS(log)
    session = VoiceSession(
        audio=audio,
        vad=vad,
        turn_analyzer=turn_analyzer,
        asr=asr,
        agent=cast(BumblehiveAgent, agent),
        tts=tts,
        observers=[_EventCollector(events)] if events is not None else (),
        opening_enabled=opening_enabled,
        inactivity_policy=inactivity_policy,
        input_level_gate=input_level_gate,
        incomplete_turn_timeout_seconds=incomplete_turn_timeout_seconds,
        backchannel_filter_enabled=backchannel_filter_enabled,
        backchannel_phrases=backchannel_phrases,
    )
    return session, audio, vad, asr, agent, tts, log


async def _start(session: VoiceSession, audio: _FakeAudio) -> asyncio.Task[None]:
    task = asyncio.create_task(session.run())
    await audio.started.wait()
    await asyncio.sleep(0)
    return task


def _emit_utterance(audio: _FakeAudio, vad: _FakeVAD) -> None:
    vad.states.extend([VADState.SPEAKING, VADState.SILENCE])
    audio.emit(_chunk(1))
    audio.emit(_chunk(2))


async def _cancel(task: asyncio.Task[None]) -> None:
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def _wait_until(predicate: Any) -> None:
    async with asyncio.timeout(1):
        while not predicate():  # noqa: ASYNC110 - generic test predicate has no event
            await asyncio.sleep(0)


async def test_emits_input_level_from_captured_microphone_audio() -> None:
    events: list[VoiceEvent] = []
    session, audio, _vad, _asr, _agent, _tts, _log = _session(events)
    task = await _start(session, audio)

    audio.emit(_chunk(16_384))
    await _wait_until(
        lambda: any(isinstance(event, InputLevelEvent) for event in events)
    )

    levels = [event.level for event in events if isinstance(event, InputLevelEvent)]
    assert levels == [pytest.approx(0.5)]

    await _cancel(task)
    levels = [event.level for event in events if isinstance(event, InputLevelEvent)]
    assert levels[-1] == 0.0


async def test_emits_adaptive_gate_diagnostics_with_the_input_level() -> None:
    events: list[VoiceEvent] = []
    session, audio, _vad, _asr, _agent, _tts, _log = _session(
        events,
        input_level_gate=AdaptiveInputLevelGate(),
    )
    task = await _start(session, audio)

    audio.emit(_chunk(1_000))
    await _wait_until(
        lambda: any(isinstance(event, InputLevelEvent) for event in events)
    )

    event = next(event for event in events if isinstance(event, InputLevelEvent))
    assert event.level_db is not None
    assert event.gate_mode == "bootstrap"
    assert event.noise_floor_db is None
    assert event.threshold_db is None
    assert event.gate_passed is True
    await _cancel(task)


async def test_incomplete_pause_keeps_one_voice_turn_until_smart_turn_completes(
) -> None:
    analyzer = _FakeTurnAnalyzer([])
    analyzer.results.extend(
        [
            TurnAnalysis(complete=False, probability=0.1),
            TurnAnalysis(complete=True, probability=0.9),
        ]
    )
    events: list[VoiceEvent] = []
    session, audio, vad, asr, _agent, _tts, _log = _session(
        events,
        turn_analyzer=analyzer,
    )
    asr.transcripts.append(Transcript("完整问题"))
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await _wait_until(lambda: len(analyzer.calls) == 1)
    await asyncio.sleep(0)
    assert asr.calls == []

    _emit_utterance(audio, vad)
    await asr.transcribed.wait()

    assert asr.calls[0].data == b"".join(_chunk(value).data for value in (1, 2, 1, 2))
    assert [event.state for event in events if isinstance(event, SpeechEvent)] == [
        SpeechState.STARTED,
        SpeechState.STOPPED,
    ]
    await _cancel(task)


async def test_voice_input_adds_vad_start_time_to_pre_speech_audio() -> None:
    session, audio, vad, asr, _agent, _tts, _log = _session()
    asr.transcripts.append(Transcript("完整问题"))
    task = await _start(session, audio)

    vad.states.extend([VADState.SILENCE] * 40 + [VADState.SPEAKING, VADState.SILENCE])
    for value in range(1, 43):
        audio.emit(_chunk(value))
    await asr.transcribed.wait()

    # 500 ms Pipecat-style pre-speech + 200 ms VAD start confirmation
    # retains the last 35 20-ms chunks before the confirmed start.
    assert asr.calls[0].data == b"".join(_chunk(value).data for value in range(6, 43))
    await _cancel(task)


async def test_incomplete_pause_is_submitted_after_turn_timeout() -> None:
    analyzer = _FakeTurnAnalyzer([])
    analyzer.results.append(TurnAnalysis(complete=False, probability=0.1))
    session, audio, vad, asr, _agent, _tts, _log = _session(
        turn_analyzer=analyzer,
        incomplete_turn_timeout_seconds=0.01,
    )
    asr.transcripts.append(Transcript("超时提交"))
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await asr.transcribed.wait()

    assert asr.calls[0].data == _chunk(1).data + _chunk(2).data
    await _cancel(task)


async def test_speech_resume_invalidates_an_in_flight_complete_prediction() -> None:
    analyzer = _FakeTurnAnalyzer([])
    analyzer.results.append(TurnAnalysis(complete=True, probability=0.9))
    analyzer.analysis_allowed.clear()
    session, audio, vad, asr, _agent, _tts, _log = _session(
        turn_analyzer=analyzer,
    )
    asr.transcripts.append(Transcript("恢复后的完整问题"))
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await analyzer.analysis_started.wait()
    vad.states.append(VADState.SPEAKING)
    audio.emit(_chunk(3))
    await _wait_until(lambda: audio.captured == 3)
    analyzer.analysis_allowed.set()
    await asyncio.sleep(0)
    assert asr.calls == []

    vad.states.append(VADState.SILENCE)
    audio.emit(_chunk(4))
    await asr.transcribed.wait()

    assert asr.calls[0].data == b"".join(_chunk(value).data for value in range(1, 5))
    await _cancel(task)


async def test_input_level_gate_only_filters_the_vad_audio_copy() -> None:
    class ClosedGate(AdaptiveInputLevelGate):
        def filter(
            self,
            chunk: AudioChunk,
            *,
            speaking: bool,
            playback_active: bool = False,
        ) -> tuple[AudioChunk, float]:
            del speaking, playback_active
            return AudioChunk(bytes(len(chunk.data)), chunk.format), -90.0

    session, audio, vad, asr, _agent, _tts, _log = _session(
        input_level_gate=ClosedGate()
    )
    asr.transcripts.append(Transcript(""))
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await asr.transcribed.wait()

    assert [chunk.data for chunk in vad.chunks] == [
        bytes(len(_chunk(1).data)),
        bytes(len(_chunk(2).data)),
    ]
    assert asr.calls[0].data == _chunk(1).data + _chunk(2).data
    await _cancel(task)


async def test_runs_turn_and_commits_history_after_playback() -> None:
    session, audio, vad, asr, agent, tts, log = _session()
    asr.transcripts.append(Transcript("用户问题"))
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await agent.result_returned.wait()
    await _wait_until(lambda: len(session.history.get_history()) == 2)

    assert agent.prompts == ["用户问题"]
    assert agent.histories == [[]]
    assert tts.parts == ["你好！", "世界"]
    assert audio.writes == [_chunk(7, output=True), _chunk(7, output=True)]
    assert session.history.get_history() == [
        {"role": "user", "content": "用户问题"},
        {"role": "assistant", "content": "你好！世界"},
    ]

    await _cancel(task)
    assert log == [
        "vad.start",
        "turn_detection.start",
        "asr.start",
        "agent.start",
        "tts.start",
        "audio.start",
        "audio.close",
        "tts.close",
        "agent.close",
        "asr.close",
        "turn_detection.close",
        "vad.close",
    ]


async def test_completed_turn_cleans_run_messages_before_committing_history() -> None:
    session, audio, vad, asr, agent, _tts, _log = _session()
    asr.transcripts.append(Transcript("用户问题"))
    agent.next_messages = [
        {"role": "system", "content": "voice runtime instructions"},
        {
            "role": "user",
            "content": (
                "用户问题\n\n<runtime_context>\n"
                "<environment_context>temporary</environment_context>\n"
                "</runtime_context>"
            ),
        },
        {"role": "assistant", "content": "你好！世界"},
    ]
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await agent.result_returned.wait()
    await _wait_until(lambda: len(session.history.get_history()) == 2)

    assert session.history.get_history() == [
        {"role": "user", "content": "用户问题"},
        {"role": "assistant", "content": "你好！世界"},
    ]

    await _cancel(task)


async def test_markdown_is_cleaned_only_for_speech() -> None:
    events: list[VoiceEvent] = []
    session, audio, vad, asr, agent, tts, _log = _session(events)
    asr.transcripts.append(Transcript("用户问题"))
    raw_answer = "# **你好**，看[文档](https://example.com)。"
    deltas = ["# **你", "好**，看[文", "档](https://example.com)。"]
    agent.next_events = [
        AgentEvent(
            kind=MODEL_STREAM_CONTENT_DELTA,
            run_id="run-1",
            payload={"delta": delta},
        )
        for delta in deltas
    ]
    agent.next_messages = [
        {"role": "user", "content": "用户问题"},
        {"role": "assistant", "content": raw_answer},
    ]
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await agent.result_returned.wait()
    await _wait_until(lambda: len(session.history.get_history()) == 2)

    assert tts.parts == ["你好，", "看文档。"]
    emitted_deltas = [
        event.delta for event in events if isinstance(event, AgentTextEvent)
    ]
    assert emitted_deltas == deltas
    assert session.history.get_history() == [
        {"role": "user", "content": "用户问题"},
        {"role": "assistant", "content": raw_answer},
    ]
    finished = [
        event
        for event in events
        if isinstance(event, PlaybackEvent) and event.state is PlaybackState.FINISHED
    ]
    assert finished[-1].spoken_text == "你好，看文档。"

    await _cancel(task)


async def test_markdown_without_speakable_text_does_not_start_synthesis() -> None:
    events: list[VoiceEvent] = []
    session, audio, vad, asr, agent, tts, _log = _session(events)
    asr.transcripts.append(Transcript("给我代码"))
    agent.next_events = [
        AgentEvent(
            kind=MODEL_STREAM_CONTENT_DELTA,
            run_id="run-1",
            payload={"delta": "```python\nprint('hello')\n```"},
        )
    ]
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await agent.result_returned.wait()
    await _wait_until(lambda: len(session.history.get_history()) == 2)

    assert tts.parts == []
    assert not any(isinstance(event, SynthesisEvent) for event in events)

    await _cancel(task)


async def test_stop_waits_for_session_shutdown() -> None:
    events: list[VoiceEvent] = []
    session, audio, _vad, _asr, _agent, _tts, log = _session(events)
    task = await _start(session, audio)

    await session.stop()

    assert task.done()
    assert not task.cancelled()
    assert log[-6:] == [
        "audio.close",
        "tts.close",
        "agent.close",
        "asr.close",
        "turn_detection.close",
        "vad.close",
    ]
    assert [event.state for event in events if isinstance(event, SessionEvent)] == [
        SessionState.STARTING,
        SessionState.READY,
        SessionState.STOPPING,
        SessionState.STOPPED,
    ]

    await session.stop()


async def test_stop_closes_active_turn_and_synthesis() -> None:
    events: list[VoiceEvent] = []
    session, audio, _vad, _asr, agent, tts, _log = _session(events)
    task = await _start(session, audio)
    tts.release_audio.clear()
    session.submit_text("用户问题")
    await tts.synthesis_started.wait()

    await session.stop()

    assert task.done()
    assert not task.cancelled()
    assert agent.turns[0].closed
    assert tts.streams[0].closed
    assert session.history.get_history() == []
    assert [event.state for event in events if isinstance(event, SynthesisEvent)] == [
        SynthesisState.STARTED,
        SynthesisState.INTERRUPTED,
    ]


async def test_request_stop_after_turn_finishes_reply_then_closes_session() -> None:
    events: list[VoiceEvent] = []
    session, audio, _vad, _asr, _agent, tts, log = _session(events)
    task = await _start(session, audio)
    tts.release_audio.clear()
    session.submit_text("关闭语音")
    await tts.synthesis_started.wait()

    session.request_stop_after_turn()
    assert not task.done()
    tts.release_audio.set()
    await asyncio.wait_for(task, timeout=1)

    assert session.history.get_history() == [
        {"role": "user", "content": "关闭语音"},
        {"role": "assistant", "content": "你好！世界"},
    ]
    assert audio.writes == [_chunk(7, output=True), _chunk(7, output=True)]
    assert log[-6:] == [
        "audio.close",
        "tts.close",
        "agent.close",
        "asr.close",
        "turn_detection.close",
        "vad.close",
    ]
    assert [event.state for event in events if isinstance(event, SessionEvent)] == [
        SessionState.STARTING,
        SessionState.READY,
        SessionState.STOPPING,
        SessionState.STOPPED,
    ]


async def test_request_stop_after_turn_closes_an_idle_session() -> None:
    events: list[VoiceEvent] = []
    session, audio, _vad, _asr, agent, _tts, _log = _session(events)
    task = await _start(session, audio)

    session.request_stop_after_turn()
    await asyncio.wait_for(task, timeout=1)

    assert agent.prompts == []
    assert [event.state for event in events if isinstance(event, SessionEvent)] == [
        SessionState.STARTING,
        SessionState.READY,
        SessionState.STOPPING,
        SessionState.STOPPED,
    ]


async def test_voice_interruption_cancels_its_stop_after_turn_request() -> None:
    events: list[VoiceEvent] = []
    session, audio, vad, asr, agent, tts, _log = _session(events)
    asr.transcripts.extend((Transcript("第一个问题"), Transcript("打断后的新问题")))
    task = await _start(session, audio)
    tts.release_audio.clear()
    _emit_utterance(audio, vad)
    await tts.synthesis_started.wait()

    session.request_stop_after_turn()
    _emit_utterance(audio, vad)
    await audio.interrupted.wait()
    await _wait_until(
        lambda: any(
            isinstance(event, TurnEvent) and event.state is TurnState.INTERRUPTED
            for event in events
        )
    )

    assert not task.done()
    await _wait_until(lambda: agent.prompts == ["第一个问题", "打断后的新问题"])

    await _cancel(task)


async def test_submit_text_runs_without_asr() -> None:
    events: list[VoiceEvent] = []
    session, audio, _vad, asr, agent, _tts, _log = _session(events)
    task = await _start(session, audio)

    session.submit_text("文字问题")
    await _wait_until(lambda: len(session.history.get_history()) == 2)

    assert asr.calls == []
    assert agent.prompts == ["文字问题"]
    assert [
        (event.source, event.text)
        for event in events
        if isinstance(event, UserInputEvent)
    ] == [(InputSource.TEXT, "文字问题")]
    await _wait_until(lambda: any(isinstance(event, MetricsEvent) for event in events))
    metrics = [event.metrics for event in events if isinstance(event, MetricsEvent)]
    assert len(metrics) == 1
    assert metrics[0].vad_confirmation_ms is None
    assert metrics[0].turn_detection_ms is None
    assert metrics[0].asr_finalization_ms is None
    assert metrics[0].asr_audio_seconds is None
    assert metrics[0].vad_stop_to_tts_first_audio_ms is None
    assert metrics[0].estimated_user_stop_to_first_playback_ms is None
    assert metrics[0].speech_first_playback_ms is None

    await _cancel(task)


async def test_submit_proactive_runs_as_hidden_source_without_interrupting() -> None:
    events: list[VoiceEvent] = []
    session, audio, _vad, asr, agent, _tts, _log = _session(events)
    task = await _start(session, audio)

    session.submit_proactive("提醒用户参加产品会议。")
    await _wait_until(lambda: len(session.history.get_history()) == 2)

    assert asr.calls == []
    assert agent.prompts[0].endswith("提醒用户参加产品会议。")
    proactive_events = [event for event in events if isinstance(event, UserInputEvent)]
    assert proactive_events[0].source is InputSource.PROACTIVE
    assert proactive_events[0].text == agent.prompts[0]
    await _cancel(task)


async def test_opening_runs_once_then_starts_followups_at_attempt_one() -> None:
    events: list[VoiceEvent] = []
    session, audio, _vad, asr, agent, _tts, _log = _session(
        events,
        opening_enabled=True,
        inactivity_policy=ConversationInactivityPolicy(
            timeout_seconds=0.01,
            max_followups=2,
        ),
    )
    task = await _start(session, audio)

    await _wait_until(lambda: len(agent.prompts) == 3)
    await asyncio.sleep(0.03)

    assert asr.calls == []
    assert "according to the system instructions" in agent.prompts[0]
    assert "attempt 1 of 2" in agent.prompts[1]
    assert "attempt 2 of 2" in agent.prompts[2]
    assert [
        event.source for event in events if isinstance(event, UserInputEvent)
    ] == [
        InputSource.OPENING,
        InputSource.FOLLOWUP,
        InputSource.FOLLOWUP,
    ]
    await _cancel(task)


async def test_inactivity_policy_validates_required_limits() -> None:
    policy = ConversationInactivityPolicy(timeout_seconds=1, max_followups=1)
    assert policy.on_exhausted is InactivityAction.WAIT
    with pytest.raises(ValueError, match="timeout_seconds"):
        ConversationInactivityPolicy(timeout_seconds=0, max_followups=1)
    with pytest.raises(ValueError, match="max_followups"):
        ConversationInactivityPolicy(timeout_seconds=1, max_followups=0)


async def test_session_without_inactivity_policy_waits_for_input() -> None:
    session, audio, _vad, _asr, agent, _tts, _log = _session()
    task = await _start(session, audio)

    await asyncio.sleep(0.03)

    assert agent.prompts == []
    await _cancel(task)


async def test_inactivity_policy_waits_for_an_assistant_reply_before_arming() -> None:
    session, audio, vad, asr, agent, _tts, _log = _session(
        inactivity_policy=ConversationInactivityPolicy(
            timeout_seconds=0.01,
            max_followups=1,
        ),
    )
    asr.transcripts.append(Transcript(""))
    task = await _start(session, audio)

    await asyncio.sleep(0.03)
    _emit_utterance(audio, vad)
    await _wait_until(lambda: len(asr.calls) == 1)
    await asyncio.sleep(0.03)

    assert agent.prompts == []
    await _cancel(task)


async def test_inactivity_policy_runs_up_to_the_configured_followups() -> None:
    events: list[VoiceEvent] = []
    session, audio, _vad, _asr, agent, _tts, _log = _session(
        events,
        inactivity_policy=ConversationInactivityPolicy(
            timeout_seconds=0.01,
            max_followups=2,
        ),
    )
    task = await _start(session, audio)
    session.submit_text("开始")

    await _wait_until(lambda: len(agent.prompts) == 3)
    await asyncio.sleep(0.03)

    assert "attempt 1 of 2" in agent.prompts[1]
    assert "attempt 2 of 2" in agent.prompts[2]
    assert [
        event.source
        for event in events
        if isinstance(event, UserInputEvent) and event.source is InputSource.FOLLOWUP
    ] == [
        InputSource.FOLLOWUP,
        InputSource.FOLLOWUP,
    ]
    await _cancel(task)


async def test_inactivity_stop_closes_after_final_response_window() -> None:
    events: list[VoiceEvent] = []
    session, audio, _vad, _asr, agent, _tts, _log = _session(
        events,
        inactivity_policy=ConversationInactivityPolicy(
            timeout_seconds=0.03,
            max_followups=1,
            on_exhausted=InactivityAction.STOP,
        ),
    )
    task = await _start(session, audio)
    session.submit_text("开始")
    await _wait_until(lambda: len(session.history.get_history()) == 2)

    await asyncio.sleep(0.01)
    assert not task.done()

    await asyncio.wait_for(task, timeout=1)

    assert len(agent.prompts) == 2
    assert [event.state for event in events if isinstance(event, SessionEvent)] == [
        SessionState.STARTING,
        SessionState.READY,
        SessionState.STOPPING,
        SessionState.STOPPED,
    ]


async def test_inactivity_farewell_runs_one_final_turn_then_closes() -> None:
    events: list[VoiceEvent] = []
    session, audio, _vad, _asr, agent, _tts, _log = _session(
        events,
        inactivity_policy=ConversationInactivityPolicy(
            timeout_seconds=0.03,
            max_followups=1,
            on_exhausted=InactivityAction.FAREWELL,
        ),
    )
    task = await _start(session, audio)
    session.submit_text("开始")
    await _wait_until(lambda: len(session.history.get_history()) == 2)

    await asyncio.sleep(0.01)
    assert len(agent.prompts) == 1

    await asyncio.wait_for(task, timeout=1)

    assert len(agent.prompts) == 3
    assert "final follow-up" in agent.prompts[2]
    assert [
        event.source
        for event in events
        if isinstance(event, UserInputEvent) and event.source is InputSource.FOLLOWUP
    ] == [
        InputSource.FOLLOWUP,
        InputSource.FOLLOWUP,
    ]


async def test_user_speech_interrupts_farewell_and_keeps_session_running() -> None:
    session, audio, vad, asr, agent, tts, _log = _session(
        inactivity_policy=ConversationInactivityPolicy(
            timeout_seconds=0.02,
            max_followups=1,
            on_exhausted=InactivityAction.FAREWELL,
        ),
    )
    asr.transcripts.append(Transcript("我还在"))
    task = await _start(session, audio)
    session.submit_text("开始")
    await _wait_until(lambda: len(session.history.get_history()) == 2)
    await _wait_until(lambda: len(session.history.get_history()) == 4)
    tts.release_audio.clear()
    await _wait_until(lambda: len(agent.prompts) == 3)
    await _wait_until(lambda: len(tts.streams) == 3)

    _emit_utterance(audio, vad)
    await _wait_until(lambda: "我还在" in agent.prompts)

    assert not task.done()
    await _cancel(task)


async def test_inactivity_wait_restarts_after_playback_finishes() -> None:
    session, audio, _vad, _asr, agent, tts, _log = _session(
        inactivity_policy=ConversationInactivityPolicy(
            timeout_seconds=0.01,
            max_followups=2,
        ),
    )
    task = await _start(session, audio)
    session.submit_text("开始")
    await _wait_until(lambda: len(session.history.get_history()) == 2)
    tts.release_audio.clear()
    await _wait_until(lambda: len(agent.prompts) == 2)

    await asyncio.sleep(0.03)
    assert len(agent.prompts) == 2

    tts.release_audio.set()
    await _wait_until(lambda: len(agent.prompts) == 3)
    await _cancel(task)


async def test_inactivity_waits_for_user_reply_playback_to_finish() -> None:
    session, audio, _vad, _asr, agent, tts, _log = _session(
        inactivity_policy=ConversationInactivityPolicy(
            timeout_seconds=0.01,
            max_followups=1,
        ),
    )
    tts.release_audio.clear()
    task = await _start(session, audio)

    session.submit_text("我在")
    await tts.synthesis_started.wait()
    await asyncio.sleep(0.03)
    assert agent.prompts == ["我在"]

    tts.release_audio.set()
    await _wait_until(lambda: len(agent.prompts) == 2)
    assert "attempt 1 of 1" in agent.prompts[1]
    await _cancel(task)


async def test_user_text_starts_a_new_inactivity_sequence() -> None:
    session, audio, _vad, _asr, agent, _tts, _log = _session(
        inactivity_policy=ConversationInactivityPolicy(
            timeout_seconds=0.01,
            max_followups=1,
        ),
    )
    task = await _start(session, audio)
    session.submit_text("开始")

    await _wait_until(lambda: len(agent.prompts) == 2)
    await asyncio.sleep(0.02)
    assert len(agent.prompts) == 2

    session.submit_text("我在")
    await _wait_until(lambda: len(agent.prompts) == 4)

    assert agent.prompts[2] == "我在"
    assert "attempt 1 of 1" in agent.prompts[3]
    await _cancel(task)


async def test_user_voice_starts_a_new_inactivity_sequence() -> None:
    session, audio, vad, asr, agent, _tts, _log = _session(
        inactivity_policy=ConversationInactivityPolicy(
            timeout_seconds=0.01,
            max_followups=1,
        ),
    )
    asr.transcripts.append(Transcript("我在"))
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await _wait_until(lambda: len(agent.prompts) == 2)

    assert agent.prompts[0] == "我在"
    assert "attempt 1 of 1" in agent.prompts[1]
    await _cancel(task)


async def test_speech_start_suspends_followup_before_audio_is_queued() -> None:
    session, audio, vad, asr, agent, _tts, _log = _session(
        inactivity_policy=ConversationInactivityPolicy(
            timeout_seconds=0.01,
            max_followups=1,
        ),
    )
    asr.transcripts.append(Transcript(""))
    task = await _start(session, audio)
    session.submit_text("开始")
    await _wait_until(lambda: len(session.history.get_history()) == 2)
    vad.states.append(VADState.SPEAKING)

    audio.emit(_chunk(1))
    await _wait_until(lambda: vad.analyzed == 1)
    await asyncio.sleep(0.03)
    assert agent.prompts == ["开始"]

    vad.states.append(VADState.SILENCE)
    audio.emit(_chunk(2))
    await _wait_until(lambda: len(asr.calls) == 1)
    await _wait_until(lambda: len(agent.prompts) == 2)
    await _cancel(task)


async def test_voice_activity_resets_followups_when_asr_returns_empty() -> None:
    session, audio, vad, asr, agent, _tts, _log = _session(
        inactivity_policy=ConversationInactivityPolicy(
            timeout_seconds=0.02,
            max_followups=2,
        ),
    )
    asr.transcripts.append(Transcript(""))
    task = await _start(session, audio)
    session.submit_text("开始")
    await _wait_until(lambda: len(agent.prompts) == 2)

    _emit_utterance(audio, vad)
    await _wait_until(lambda: len(asr.calls) == 1)
    await _wait_until(lambda: len(agent.prompts) == 3)

    assert "attempt 1 of 2" in agent.prompts[1]
    assert "attempt 1 of 2" in agent.prompts[2]
    await _cancel(task)


async def test_asr_failure_finishes_voice_activity_and_rearms_inactivity() -> None:
    session, audio, vad, asr, agent, _tts, _log = _session(
        inactivity_policy=ConversationInactivityPolicy(
            timeout_seconds=0.02,
            max_followups=1,
        ),
    )
    asr.fail_write = True
    task = await _start(session, audio)
    session.submit_text("开始")
    await _wait_until(lambda: len(session.history.get_history()) == 2)

    _emit_utterance(audio, vad)
    await _wait_until(lambda: len(agent.prompts) == 2)

    assert agent.prompts[0] == "开始"
    assert "attempt 1 of 1" in agent.prompts[1]
    await _cancel(task)


async def test_submit_proactive_rejects_busy_session_instead_of_interrupting() -> None:
    session, audio, _vad, _asr, agent, tts, _log = _session()
    task = await _start(session, audio)
    tts.release_audio.clear()
    session.submit_text("正在处理的问题")
    await tts.synthesis_started.wait()

    with pytest.raises(RuntimeError, match="busy"):
        session.submit_proactive("主动提醒")

    assert agent.prompts == ["正在处理的问题"]
    assert not audio.interrupted.is_set()
    await _cancel(task)


async def test_submit_proactive_rejects_user_speech_before_segment_is_queued() -> None:
    session, audio, vad, _asr, _agent, _tts, _log = _session()
    task = await _start(session, audio)
    vad.states.append(VADState.SPEAKING)

    audio.emit(_chunk(1))
    await _wait_until(lambda: vad.analyzed == 1)

    with pytest.raises(RuntimeError, match="busy"):
        session.submit_proactive("主动提醒")

    await _cancel(task)


async def test_submit_proactive_rejects_voice_input_during_asr() -> None:
    session, audio, vad, asr, _agent, _tts, _log = _session()
    asr.transcripts.append(Transcript("用户问题"))
    asr.transcription_allowed.clear()
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await _wait_until(lambda: len(asr.calls) == 1)

    with pytest.raises(RuntimeError, match="busy"):
        session.submit_proactive("主动提醒")

    asr.transcription_allowed.set()
    await _cancel(task)


async def test_text_and_voice_inputs_share_history() -> None:
    session, audio, vad, asr, agent, _tts, _log = _session()
    asr.transcripts.append(Transcript("语音问题"))
    task = await _start(session, audio)

    session.submit_text("文字问题")
    await _wait_until(lambda: len(session.history.get_history()) == 2)
    _emit_utterance(audio, vad)
    await _wait_until(lambda: len(agent.prompts) == 2)

    assert agent.prompts == ["文字问题", "语音问题"]
    assert agent.histories[1] == [
        {"role": "user", "content": "文字问题"},
        {"role": "assistant", "content": "你好！世界"},
    ]

    await _cancel(task)


async def test_submit_text_validates_session_and_queue() -> None:
    session, audio, _vad, _asr, _agent, tts, _log = _session()

    with pytest.raises(RuntimeError, match="not ready"):
        session.submit_text("问题")

    task = await _start(session, audio)
    with pytest.raises(ValueError, match="must not be empty"):
        session.submit_text("  ")

    tts.release_audio.clear()
    session.submit_text("第一个问题")
    await tts.synthesis_started.wait()
    session.submit_text("第二个问题")
    with pytest.raises(asyncio.QueueFull):
        session.submit_text("第三个问题")

    await _cancel(task)


async def test_submit_text_interrupts_active_reply_before_next_prompt() -> None:
    events: list[VoiceEvent] = []
    session, audio, _vad, _asr, agent, tts, _log = _session(events)
    task = await _start(session, audio)
    tts.release_audio.clear()
    session.submit_text("第一个问题")
    await tts.synthesis_started.wait()

    session.submit_text("第二个问题")

    await audio.interrupted.wait()
    await _wait_until(lambda: agent.prompts == ["第一个问题", "第二个问题"])
    turn_states = [event.state for event in events if isinstance(event, TurnEvent)]
    assert turn_states[:3] == [
        TurnState.STARTED,
        TurnState.INTERRUPTED,
        TurnState.STARTED,
    ]

    await _cancel(task)


async def test_manual_interrupt_stops_only_active_turn() -> None:
    events: list[VoiceEvent] = []
    session, audio, _vad, _asr, agent, tts, _log = _session(events)
    task = await _start(session, audio)
    tts.release_audio.clear()
    session.submit_text("第一个问题")
    await tts.synthesis_started.wait()

    assert session.interrupt()
    await audio.interrupted.wait()
    await _wait_until(
        lambda: any(
            isinstance(event, TurnEvent) and event.state is TurnState.INTERRUPTED
            for event in events
        )
    )

    assert not task.done()
    assert not session.interrupt()
    assert agent.turns[0].closed
    assert tts.streams[0].closed
    assert [event.state for event in events if isinstance(event, TurnEvent)] == [
        TurnState.STARTED,
        TurnState.INTERRUPTED,
    ]
    assert [event.state for event in events if isinstance(event, SynthesisEvent)] == [
        SynthesisState.STARTED,
        SynthesisState.INTERRUPTED,
    ]

    await _cancel(task)


async def test_emits_ordered_desktop_events_and_turn_metrics() -> None:
    events: list[VoiceEvent] = []
    session, audio, vad, asr, agent, _tts, _log = _session(events)
    asr.transcripts.append(Transcript("用户问题", language="zh"))
    agent.next_events = [
        AgentEvent(
            kind=MODEL_REQUEST_STARTED,
            run_id="run-1",
            payload={
                "request": {
                    "messages": [
                        {"role": "system", "content": "系统提示"},
                        {"role": "user", "content": "用户问题"},
                    ]
                }
            },
        ),
        AgentEvent(
            kind=MODEL_STREAM_CONTENT_DELTA,
            run_id="run-1",
            payload={"delta": "你好"},
        ),
        AgentEvent(
            kind=MODEL_STREAM_CONTENT_DELTA,
            run_id="run-1",
            payload={"delta": "！世界"},
        ),
    ]
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await agent.result_returned.wait()
    await _wait_until(lambda: len(session.history.get_history()) == 2)
    await _cancel(task)

    session_states = [
        event.state for event in events if isinstance(event, SessionEvent)
    ]
    assert session_states == [
        SessionState.STARTING,
        SessionState.READY,
        SessionState.STOPPING,
        SessionState.STOPPED,
    ]
    assert {event.session_id for event in events} == {session.session_id}

    ready_components = [
        event.component
        for event in events
        if isinstance(event, ComponentEvent) and event.state is ComponentState.READY
    ]
    assert ready_components == [
        Component.VAD,
        Component.TURN_DETECTION,
        Component.ASR,
        Component.AGENT,
        Component.TTS,
        Component.AUDIO,
    ]
    assert [event.state for event in events if isinstance(event, SpeechEvent)] == [
        SpeechState.STARTED,
        SpeechState.STOPPED,
    ]
    assert [event.text for event in events if isinstance(event, TranscriptEvent)] == [
        "用户问题"
    ]
    assert [
        event.is_final for event in events if isinstance(event, TranscriptEvent)
    ] == [True]
    assert [
        (event.source, event.text)
        for event in events
        if isinstance(event, UserInputEvent)
    ] == [(InputSource.VOICE, "用户问题")]
    assert [event.delta for event in events if isinstance(event, AgentTextEvent)] == [
        "你好",
        "！世界",
    ]
    requests = [event for event in events if isinstance(event, AgentRequestEvent)]
    assert len(requests) == 1
    assert requests[0].messages == (
        {"role": "system", "content": "系统提示"},
        {"role": "user", "content": "用户问题"},
    )
    assert [event.state for event in events if isinstance(event, TurnEvent)] == [
        TurnState.STARTED,
        TurnState.COMPLETED,
    ]
    assert [event.state for event in events if isinstance(event, PlaybackEvent)] == [
        PlaybackState.STARTED,
        PlaybackState.PROGRESS,
        PlaybackState.PROGRESS,
        PlaybackState.FINISHED,
    ]
    synthesis = [event for event in events if isinstance(event, SynthesisEvent)]
    assert [event.state for event in synthesis] == [
        SynthesisState.STARTED,
        SynthesisState.FIRST_AUDIO,
        SynthesisState.FINISHED,
    ]
    assert synthesis[0].elapsed_ms == 0.0

    metrics = [event.metrics for event in events if isinstance(event, MetricsEvent)]
    assert len(metrics) == 1
    assert metrics[0].asr_audio_seconds == pytest.approx(0.04)
    assert metrics[0].asr_usage == {
        "input_audio_seconds": pytest.approx(0.04),
        "output_characters": 4,
    }
    assert metrics[0].agent_request_preparation_ms is not None
    assert metrics[0].agent_first_token_ms is not None
    assert metrics[0].vad_confirmation_ms == pytest.approx(200, abs=0.1)
    assert metrics[0].turn_detection_ms is not None
    assert metrics[0].asr_finalization_ms is not None
    assert metrics[0].speech_first_playback_ms is not None
    assert metrics[0].llm_first_token_ms is not None
    assert metrics[0].tts_first_audio_ms is not None
    assert metrics[0].vad_stop_to_tts_first_audio_ms is not None
    assert metrics[0].estimated_user_stop_to_first_playback_ms is not None
    assert metrics[0].estimated_user_stop_to_first_playback_ms >= (
        metrics[0].vad_stop_to_tts_first_audio_ms + 199.9
    )
    phases = (
        metrics[0].vad_confirmation_ms,
        metrics[0].turn_detection_ms,
        metrics[0].asr_finalization_ms,
        metrics[0].agent_first_token_ms,
        metrics[0].speech_first_playback_ms,
    )
    assert metrics[0].estimated_user_stop_to_first_playback_ms == pytest.approx(
        sum(cast(float, phase) for phase in phases),
        abs=0.5,
    )
    assert metrics[0].tts_usage == {
        "input_characters": 5,
        "audio_bytes": 1_280,
    }


async def test_streaming_transcripts_are_emitted_as_cumulative_interims() -> None:
    updates: list[tuple[str, str | None, bool]] = []

    async def transcripts() -> AsyncIterator[Transcript]:
        yield Transcript("你", is_final=False)
        yield Transcript("你好", is_final=False)
        yield Transcript("你好", is_final=True)
        yield Transcript("世", is_final=False)
        yield Transcript("世界", is_final=True)

    text, language = await _collect_transcripts(
        cast(Any, transcripts()),
        on_update=lambda text, language, is_final: updates.append(
            (text, language, is_final)
        ),
    )

    assert text == "你好世界"
    assert language is None
    assert updates == [
        ("你", None, False),
        ("你好", None, False),
        ("你好", None, True),
        ("你好世", None, False),
        ("你好世界", None, True),
    ]


async def test_speech_content_normalization_handles_multilingual_punctuation() -> None:
    assert _normalize_speech_content("……？！") == ""
    assert _normalize_speech_content("嗯，嗯。") == "嗯嗯"
    assert _normalize_speech_content("ｕｈ－ｈｕｈ～") == "uhhuh"
    assert _normalize_speech_content("うん、うん。") == "うんうん"
    assert _normalize_speech_content("هذا صحيح؟") == "هذاصحيح"


async def test_streaming_recognition_drains_success_without_cancelling() -> None:
    class StreamOwner:
        def __init__(self) -> None:
            self.active = False

        def recognize(self) -> "ContractStream":
            if self.active:
                raise RuntimeError("one active stream")
            self.active = True
            return ContractStream(self)

    class ContractStream:
        def __init__(self, owner: StreamOwner) -> None:
            self.owner = owner
            self.finished = asyncio.Event()
            self.emitted = False
            self.close_calls = 0

        def __aiter__(self) -> Self:
            return self

        async def __anext__(self) -> Transcript:
            await self.finished.wait()
            if not self.emitted:
                self.emitted = True
                return Transcript("完成", language="zh")
            self.owner.active = False
            raise StopAsyncIteration

        async def write(self, audio: AudioChunk) -> None:
            del audio

        async def finish(self) -> None:
            self.finished.set()

        async def result(self) -> ASRResult:
            await self.finished.wait()
            return ASRResult(0.02, 2, True)

        async def aclose(self) -> None:
            self.close_calls += 1
            self.owner.active = False
            self.finished.set()

    owner = StreamOwner()
    first = owner.recognize()
    recognition = _StreamingRecognition(
        first,
        on_update=lambda _text, _lang, _final: None,
    )

    result = await recognition.finish()

    assert result.text == "完成"
    assert result.language == "zh"
    assert result.asr_result == ASRResult(0.02, 2, True)
    assert not owner.active
    assert first.close_calls == 0

    second = owner.recognize()
    await second.aclose()


async def test_emits_text_as_queued_audio_is_actually_played() -> None:
    events: list[VoiceEvent] = []
    session, audio, vad, asr, _agent, _tts, _log = _session(events)
    asr.transcripts.append(Transcript("用户问题"))
    audio.queue_playback()
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await _wait_until(lambda: len(audio.writes) == 2)
    await asyncio.sleep(0.03)

    progress = [
        event
        for event in events
        if isinstance(event, PlaybackEvent) and event.state is PlaybackState.PROGRESS
    ]
    assert progress == []

    audio.advance_playback(audio.writes[0].frame_count)
    await _wait_until(
        lambda: any(
            isinstance(event, PlaybackEvent)
            and event.state is PlaybackState.PROGRESS
            and event.spoken_text == "你好！"
            for event in events
        )
    )

    audio.advance_playback(audio.writes[1].frame_count)
    await _wait_until(
        lambda: any(
            isinstance(event, PlaybackEvent)
            and event.state is PlaybackState.PROGRESS
            and event.spoken_text == "你好！世界"
            for event in events
        )
    )
    audio.finish_playback()
    await _wait_until(lambda: len(session.history.get_history()) == 2)

    deltas = [
        event.delta
        for event in events
        if isinstance(event, PlaybackEvent) and event.state is PlaybackState.PROGRESS
    ]
    assert deltas == ["你好！", "世界"]

    await _cancel(task)
    assert not any(
        running.get_name() == "lalk-playback-progress"
        for running in asyncio.all_tasks()
        if running is not asyncio.current_task()
    )


async def test_tts_marks_are_consumed_while_audio_output_is_blocked() -> None:
    session, audio, vad, asr, _agent, tts, _log = _session()
    asr.transcripts.append(Transcript("用户问题"))
    audio.write_allowed.clear()
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await audio.write_started.wait()

    async with asyncio.timeout(1):
        await tts.text_marked.wait()

    assert audio.writes == []

    audio.write_allowed.set()
    await _wait_until(lambda: len(session.history.get_history()) == 2)
    await _cancel(task)


async def test_emits_component_failure_and_fatal_error() -> None:
    events: list[VoiceEvent] = []
    session, _audio, _vad, _asr, agent, _tts, _log = _session(events)
    agent.fail_start = True

    with pytest.raises(RuntimeError, match="agent start failed"):
        await session.run()

    failures = [
        event
        for event in events
        if isinstance(event, ComponentEvent) and event.state is ComponentState.FAILED
    ]
    assert len(failures) == 1
    assert failures[0].component is Component.AGENT

    errors = [event for event in events if isinstance(event, ErrorEvent)]
    assert len(errors) == 1
    assert errors[0].component is Component.AGENT
    assert errors[0].operation == "start"
    assert errors[0].fatal


async def test_emits_tool_arguments_and_results() -> None:
    events: list[VoiceEvent] = []
    session, audio, vad, asr, agent, _tts, _log = _session(events)
    asr.transcripts.append(Transcript("查天气"))
    tool_call = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "weather", "arguments": "{}"},
            }
        ],
    }
    tool_result = {
        "role": "tool",
        "tool_call_id": "call-1",
        "name": "weather",
        "content": "晴天",
    }
    agent.next_events = [
        AgentEvent(
            kind=MODEL_RESPONSE_FINISHED,
            run_id="run-1",
            payload={"message": tool_call},
        ),
        AgentEvent(kind=TOOL_CALLS_STARTED, run_id="run-1"),
        AgentEvent(
            kind=TOOL_CALL_STARTED,
            run_id="run-1",
            payload={
                "tool_call": {
                    "call_id": "call-1",
                    "name": "weather",
                    "arguments": {"city": "北京"},
                }
            },
        ),
        AgentEvent(
            kind=TOOL_CALL_FINISHED,
            run_id="run-1",
            payload={
                "tool_result": tool_result,
                "ok": True,
                "duration_s": 0.012,
                "file_changes": [
                    {
                        "path": "sale_agent.md",
                        "added": 1,
                        "deleted": 1,
                        "unified_diff": (
                            "--- sale_agent.md\n"
                            "+++ sale_agent.md\n"
                            "@@ -8 +8 @@\n"
                            "-先介绍节省成本\n"
                            "+先询问客户每年招聘多少人"
                        ),
                    }
                ],
            },
        ),
        AgentEvent(kind=TOOL_CALLS_FINISHED, run_id="run-1"),
        AgentEvent(kind=MODEL_REQUEST_STARTED, run_id="run-1"),
        AgentEvent(
            kind=MODEL_STREAM_CONTENT_DELTA,
            run_id="run-1",
            payload={"delta": "晴天。"},
        ),
    ]
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await agent.result_returned.wait()
    await _wait_until(lambda: len(session.history.get_history()) == 2)
    await _cancel(task)

    started = [event for event in events if isinstance(event, ToolCallStartedEvent)]
    finished = [event for event in events if isinstance(event, ToolCallFinishedEvent)]
    assert started == [
        ToolCallStartedEvent(
            session_id=session.session_id,
            turn_id=1,
            name="weather",
            call_id="call-1",
            arguments={"city": "北京"},
            timestamp=started[0].timestamp,
        )
    ]
    assert finished == [
        ToolCallFinishedEvent(
            session_id=session.session_id,
            turn_id=1,
            name="weather",
            call_id="call-1",
            result="晴天",
            elapsed_ms=12.0,
            succeeded=True,
            file_changes=(
                {
                    "path": "sale_agent.md",
                    "added": 1,
                    "deleted": 1,
                    "unified_diff": (
                        "--- sale_agent.md\n"
                        "+++ sale_agent.md\n"
                        "@@ -8 +8 @@\n"
                        "-先介绍节省成本\n"
                        "+先询问客户每年招聘多少人"
                    ),
                },
            ),
            timestamp=finished[0].timestamp,
        )
    ]


async def test_uses_completed_history_for_the_next_turn() -> None:
    session, audio, vad, asr, agent, _tts, _log = _session()
    asr.transcripts.extend((Transcript("第一个问题"), Transcript("第二个问题")))
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await _wait_until(lambda: len(session.history.get_history()) >= 2)

    _emit_utterance(audio, vad)
    await _wait_until(lambda: len(agent.prompts) >= 2)

    assert agent.histories[1] == [
        {"role": "user", "content": "第一个问题"},
        {"role": "assistant", "content": "你好！世界"},
    ]

    await _cancel(task)


@pytest.mark.parametrize(
    (
        "pre_tool_text",
        "post_tool_deltas",
        "expected_spoken_text",
        "expected_visible_deltas",
    ),
    [
        pytest.param(
            "好的，再见。",
            ["再", "见。"],
            "好的，再见。",
            ["好的，再见。"],
            id="pre-tool-farewell-wins",
        ),
        pytest.param(
            None,
            ["好的，", "再见。"],
            "好的，再见。",
            ["好的，", "再见。"],
            id="post-tool-farewell-plays-when-silent",
        ),
        pytest.param(
            "   ",
            ["再见。"],
            "再见。",
            ["   ", "再见。"],
            id="whitespace-does-not-count-as-speech",
        ),
        pytest.param(
            "已经处理完毕。",
            ["再见。", "祝您生活愉快。"],
            "已经处理完毕。",
            ["已经处理完毕。"],
            id="all-post-tool-deltas-are-suppressed",
        ),
    ],
)
async def test_end_voice_session_plays_exactly_one_farewell(
    pre_tool_text: str | None,
    post_tool_deltas: list[str],
    expected_spoken_text: str,
    expected_visible_deltas: list[str],
) -> None:
    events: list[VoiceEvent] = []
    session, audio, vad, asr, agent, tts, _log = _session(events)
    asr.transcripts.append(Transcript("结束会话"))
    post_tool_text = "".join(post_tool_deltas)
    tool_call = {
        "role": "assistant",
        "content": pre_tool_text,
        "tool_calls": [
            {
                "id": "call-end",
                "type": "function",
                "function": {"name": "end_voice_session", "arguments": "{}"},
            }
        ],
    }
    tool_result = {
        "role": "tool",
        "tool_call_id": "call-end",
        "name": "end_voice_session",
        "content": '{"ending":true}',
    }
    pre_tool_events = (
        [
            AgentEvent(
                kind=MODEL_STREAM_CONTENT_DELTA,
                run_id="run-1",
                payload={"delta": pre_tool_text},
            )
        ]
        if pre_tool_text is not None
        else []
    )
    agent.next_events = [
        AgentEvent(kind=MODEL_REQUEST_STARTED, run_id="run-1"),
        *pre_tool_events,
        AgentEvent(
            kind=MODEL_RESPONSE_FINISHED,
            run_id="run-1",
            payload={"message": tool_call},
        ),
        AgentEvent(kind=TOOL_CALLS_STARTED, run_id="run-1"),
        AgentEvent(
            kind=TOOL_CALL_STARTED,
            run_id="run-1",
            payload={
                "tool_call": {
                    "call_id": "call-end",
                    "name": "end_voice_session",
                    "arguments": {},
                }
            },
        ),
        AgentEvent(
            kind=TOOL_CALL_FINISHED,
            run_id="run-1",
            payload={
                "tool_result": tool_result,
                "ok": True,
                "duration_s": 0.001,
            },
        ),
        AgentEvent(kind=TOOL_CALLS_FINISHED, run_id="run-1"),
        AgentEvent(kind=MODEL_REQUEST_STARTED, run_id="run-1"),
        *[
            AgentEvent(
                kind=MODEL_STREAM_CONTENT_DELTA,
                run_id="run-1",
                payload={"delta": delta},
            )
            for delta in post_tool_deltas
        ],
        AgentEvent(
            kind=MODEL_RESPONSE_FINISHED,
            run_id="run-1",
            payload={"message": {"role": "assistant", "content": post_tool_text}},
        ),
    ]
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await agent.result_returned.wait()
    await _wait_until(lambda: "".join(tts.parts) == expected_spoken_text)

    assert [
        event.delta for event in events if isinstance(event, AgentTextEvent)
    ] == expected_visible_deltas

    await _cancel(task)


async def test_non_terminal_tool_keeps_text_before_and_after_tool() -> None:
    events: list[VoiceEvent] = []
    session, audio, vad, asr, agent, tts, _log = _session(events)
    asr.transcripts.append(Transcript("查询天气"))
    tool_call = {
        "role": "assistant",
        "content": "我帮您查一下。",
        "tool_calls": [
            {
                "id": "call-weather",
                "type": "function",
                "function": {"name": "get_weather", "arguments": "{}"},
            }
        ],
    }
    tool_result = {
        "role": "tool",
        "tool_call_id": "call-weather",
        "name": "get_weather",
        "content": '{"condition":"sunny"}',
    }
    agent.next_events = [
        AgentEvent(kind=MODEL_REQUEST_STARTED, run_id="run-1"),
        AgentEvent(
            kind=MODEL_STREAM_CONTENT_DELTA,
            run_id="run-1",
            payload={"delta": "我帮您查一下。"},
        ),
        AgentEvent(
            kind=MODEL_RESPONSE_FINISHED,
            run_id="run-1",
            payload={"message": tool_call},
        ),
        AgentEvent(kind=TOOL_CALLS_STARTED, run_id="run-1"),
        AgentEvent(
            kind=TOOL_CALL_STARTED,
            run_id="run-1",
            payload={
                "tool_call": {
                    "call_id": "call-weather",
                    "name": "get_weather",
                    "arguments": {},
                }
            },
        ),
        AgentEvent(
            kind=TOOL_CALL_FINISHED,
            run_id="run-1",
            payload={
                "tool_result": tool_result,
                "ok": True,
                "duration_s": 0.001,
            },
        ),
        AgentEvent(kind=TOOL_CALLS_FINISHED, run_id="run-1"),
        AgentEvent(kind=MODEL_REQUEST_STARTED, run_id="run-1"),
        AgentEvent(
            kind=MODEL_STREAM_CONTENT_DELTA,
            run_id="run-1",
            payload={"delta": "今天是晴天。"},
        ),
        AgentEvent(
            kind=MODEL_RESPONSE_FINISHED,
            run_id="run-1",
            payload={
                "message": {"role": "assistant", "content": "今天是晴天。"}
            },
        ),
    ]
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await agent.result_returned.wait()
    await _wait_until(lambda: "".join(tts.parts) == "我帮您查一下。今天是晴天。")

    assert [
        event.delta for event in events if isinstance(event, AgentTextEvent)
    ] == ["我帮您查一下。", "今天是晴天。"]

    await _cancel(task)


async def test_capture_continues_while_response_is_playing() -> None:
    session, audio, vad, asr, _agent, tts, _log = _session()
    asr.transcripts.append(Transcript("用户问题"))
    tts.release_audio.clear()
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await tts.synthesis_started.wait()
    audio.emit(_chunk(3))
    audio.emit(_chunk(4))
    audio.emit(_chunk(5))

    await _wait_until(lambda: vad.analyzed >= 5)

    assert vad.analyzed == 5

    tts.release_audio.set()
    await _cancel(task)


async def test_streaming_backchannel_interrupts_when_substantive_text_arrives() -> None:
    events: list[VoiceEvent] = []
    session, audio, vad, asr, _agent, _tts, _log = _session(
        events,
        backchannel_filter_enabled=True,
    )
    asr.supports_interim_transcripts = True
    audio.queue_playback()
    task = await _start(session, audio)
    session.submit_text("请继续说明")
    await audio.write_started.wait()

    vad.states.append(VADState.SPEAKING)
    audio.emit(_chunk(1))
    await _wait_until(lambda: len(asr.streams) == 1)
    stream = asr.streams[0]

    stream.emit(Transcript("嗯哼。", is_final=False))
    await asyncio.sleep(0)
    assert audio.interrupt_calls == 0

    stream.emit(Transcript("嗯哼，但是这个不对。", is_final=False))
    await audio.interrupted.wait()

    assert audio.interrupt_calls == 1
    assert [event.state for event in events if isinstance(event, SpeechEvent)] == [
        SpeechState.STARTED
    ]
    assert [event.text for event in events if isinstance(event, TranscriptEvent)] == [
        "嗯哼，但是这个不对。"
    ]
    await _cancel(task)


async def test_streaming_backchannel_waits_for_substantive_final_text() -> None:
    events: list[VoiceEvent] = []
    session, audio, vad, asr, _agent, _tts, _log = _session(
        events,
        backchannel_filter_enabled=True,
    )
    asr.supports_interim_transcripts = True
    asr.transcripts.append(
        Transcript("嗯哼，但是这个不对。", is_final=True)
    )
    audio.queue_playback()
    task = await _start(session, audio)
    session.submit_text("请继续说明")
    await audio.write_started.wait()

    vad.states.append(VADState.SPEAKING)
    audio.emit(_chunk(1))
    await _wait_until(lambda: len(asr.streams) == 1)
    stream = asr.streams[0]
    stream.emit(Transcript("嗯哼。", is_final=False))
    await asyncio.sleep(0)
    assert audio.interrupt_calls == 0

    vad.states.append(VADState.SILENCE)
    audio.emit(_chunk(2))
    await audio.interrupted.wait()
    await _wait_until(
        lambda: any(
            isinstance(event, TranscriptEvent)
            and event.is_final
            and event.text == "嗯哼，但是这个不对。"
            for event in events
        )
    )

    assert audio.interrupt_calls == 1
    assert [event.state for event in events if isinstance(event, SpeechEvent)] == [
        SpeechState.STARTED,
        SpeechState.STOPPED,
    ]
    await _cancel(task)


@pytest.mark.parametrize(
    ("phrases", "interim", "final"),
    [
        (None, "嗯。", "嗯。"),
        (None, "……？！", "……？！"),
        ({"好的"}, "好", "好的。"),
        ({"うんうん"}, "うん、うん。", "うん、うん。"),
    ],
)
async def test_streaming_backchannel_or_punctuation_is_discarded(
    phrases: Collection[str] | None,
    interim: str,
    final: str,
) -> None:
    events: list[VoiceEvent] = []
    analyzer = _FakeTurnAnalyzer([])
    session, audio, vad, asr, _agent, _tts, _log = _session(
        events,
        turn_analyzer=analyzer,
        backchannel_filter_enabled=True,
        backchannel_phrases=phrases,
    )
    asr.supports_interim_transcripts = True
    asr.transcripts.append(Transcript(final, is_final=True))
    audio.queue_playback()
    task = await _start(session, audio)
    session.submit_text("请继续说明")
    await audio.write_started.wait()

    vad.states.append(VADState.SPEAKING)
    audio.emit(_chunk(1))
    await _wait_until(lambda: len(asr.streams) == 1)
    stream = asr.streams[0]
    stream.emit(Transcript(interim, is_final=False))
    await asyncio.sleep(0)

    vad.states.append(VADState.SILENCE)
    audio.emit(_chunk(2))
    await asr.transcribed.wait()

    assert audio.interrupt_calls == 0
    assert len(analyzer.calls) == 1
    assert not stream.closed
    assert not any(isinstance(event, SpeechEvent) for event in events)
    assert not any(isinstance(event, TranscriptEvent) for event in events)
    await _cancel(task)


@pytest.mark.parametrize(
    ("filter_enabled", "supports_interim"),
    [(False, True), (True, False)],
)
async def test_backchannel_filter_falls_back_to_vad_when_unavailable(
    filter_enabled: bool,
    supports_interim: bool,
) -> None:
    session, audio, vad, asr, _agent, _tts, _log = _session(
        backchannel_filter_enabled=filter_enabled,
    )
    asr.supports_interim_transcripts = supports_interim
    audio.queue_playback()
    task = await _start(session, audio)
    session.submit_text("请继续说明")
    await audio.write_started.wait()

    vad.states.append(VADState.SPEAKING)
    audio.emit(_chunk(1))
    await audio.interrupted.wait()

    assert audio.interrupt_calls == 1
    await _cancel(task)


@pytest.mark.parametrize(
    ("final", "expected_interrupts"),
    [
        ("嗯嗯。", 0),
        ("等一下。", 1),
        ("", 0),
    ],
)
async def test_streaming_filter_waits_for_final_without_interim_transcript(
    final: str,
    expected_interrupts: int,
) -> None:
    session, audio, vad, asr, _agent, _tts, _log = _session(
        backchannel_filter_enabled=True,
    )
    asr.supports_interim_transcripts = True
    asr.transcripts.append(Transcript(final, is_final=True))
    asr.transcription_allowed.clear()
    audio.queue_playback()
    task = await _start(session, audio)
    session.submit_text("请继续说明")
    await audio.write_started.wait()

    vad.states.append(VADState.SPEAKING)
    audio.emit(_chunk(1))
    await _wait_until(lambda: len(asr.streams) == 1)
    assert audio.interrupt_calls == 0

    vad.states.append(VADState.SILENCE)
    audio.emit(_chunk(2))
    await _wait_until(lambda: len(asr.calls) == 1)

    assert audio.interrupt_calls == 0

    asr.transcription_allowed.set()
    await asr.transcribed.wait()
    if expected_interrupts:
        await audio.interrupted.wait()
    else:
        await _wait_until(lambda: not asr.streams[0]._outputs.qsize())

    assert audio.interrupt_calls == expected_interrupts
    await _cancel(task)


async def test_user_speech_interrupts_playback_and_commits_only_heard_text() -> None:
    class RecordingGate(AdaptiveInputLevelGate):
        def __init__(self) -> None:
            super().__init__()
            self.playback_states: list[bool] = []

        def filter(
            self,
            chunk: AudioChunk,
            *,
            speaking: bool,
            playback_active: bool = False,
        ) -> tuple[AudioChunk, float]:
            del speaking
            self.playback_states.append(playback_active)
            return chunk, -30.0

    events: list[VoiceEvent] = []
    gate = RecordingGate()
    session, audio, vad, asr, agent, tts, _log = _session(
        events,
        input_level_gate=gate,
    )
    asr.transcripts.extend((Transcript("第一个问题"), Transcript("打断问题")))
    tts.pause_after_parts = 1
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await tts.text_marked.wait()
    _emit_utterance(audio, vad)

    await audio.interrupted.wait()
    await _wait_until(lambda: len(agent.prompts) >= 2)

    assert audio.interrupt_calls == 1
    assert any(gate.playback_states)
    assert audio.writes == [_chunk(7, output=True)]
    assert agent.turns[0].closed
    assert tts.streams[0].closed
    assert agent.histories[1] == [
        {"role": "user", "content": "第一个问题"},
        {"role": "assistant", "content": "你好！"},
    ]

    await _wait_until(
        lambda: any(
            isinstance(event, PlaybackEvent)
            and event.turn_id == 1
            and event.state is PlaybackState.INTERRUPTED
            for event in events
        )
    )
    first_turn_event_count = sum(
        isinstance(event, PlaybackEvent) and event.turn_id == 1 for event in events
    )
    await asyncio.sleep(0.05)
    assert (
        sum(isinstance(event, PlaybackEvent) and event.turn_id == 1 for event in events)
        == first_turn_event_count
    )

    await _cancel(task)


async def test_markdown_interruption_commits_cleaned_heard_text() -> None:
    session, audio, vad, asr, agent, tts, _log = _session()
    asr.transcripts.extend((Transcript("第一个问题"), Transcript("打断问题")))
    agent.next_events = [
        AgentEvent(
            kind=MODEL_STREAM_CONTENT_DELTA,
            run_id="run-1",
            payload={"delta": "**已经播放。**后续内容"},
        )
    ]
    tts.pause_after_parts = 1
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await tts.text_marked.wait()
    _emit_utterance(audio, vad)

    await audio.interrupted.wait()
    await _wait_until(lambda: len(agent.prompts) >= 2)

    assert agent.histories[1] == [
        {"role": "user", "content": "第一个问题"},
        {"role": "assistant", "content": "已经播放。"},
    ]

    await _cancel(task)


async def test_interruption_before_audio_commits_only_user_message() -> None:
    session, audio, vad, asr, agent, tts, _log = _session()
    asr.transcripts.extend((Transcript("第一个问题"), Transcript("打断问题")))
    tts.release_audio.clear()
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await agent.result_returned.wait()
    _emit_utterance(audio, vad)

    await audio.interrupted.wait()
    await _wait_until(lambda: len(agent.prompts) >= 2)

    assert audio.writes == []
    assert agent.histories[1] == [
        {"role": "user", "content": "第一个问题"},
    ]

    await _cancel(task)


async def test_interruption_without_tts_marks_is_conservative() -> None:
    session, audio, vad, asr, agent, tts, _log = _session()
    asr.transcripts.extend((Transcript("第一个问题"), Transcript("打断问题")))
    keep_agent_open = asyncio.Event()
    agent.next_events = [
        AgentEvent(
            kind=MODEL_STREAM_CONTENT_DELTA,
            run_id="run-1",
            payload={"delta": "已经播放。"},
        ),
        keep_agent_open,
    ]
    tts.emit_text_marks = False
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await _wait_until(lambda: bool(audio.writes))
    _emit_utterance(audio, vad)

    await audio.interrupted.wait()
    await _wait_until(lambda: len(agent.prompts) >= 2)

    assert agent.histories[1] == [
        {"role": "user", "content": "第一个问题"},
    ]

    await _cancel(task)


async def test_interruption_waits_for_active_tool_and_preserves_tool_messages() -> None:
    session, audio, vad, asr, agent, _tts, _log = _session()
    asr.transcripts.extend((Transcript("查天气"), Transcript("换个问题")))
    tool_finished = asyncio.Event()
    tool_call = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "weather", "arguments": "{}"},
            }
        ],
    }
    tool_result = {
        "role": "tool",
        "tool_call_id": "call-1",
        "name": "weather",
        "content": "晴天",
    }
    agent.next_events = [
        AgentEvent(
            kind=MODEL_RESPONSE_FINISHED,
            run_id="run-1",
            payload={"message": tool_call},
        ),
        AgentEvent(kind=TOOL_CALLS_STARTED, run_id="run-1"),
        tool_finished,
        AgentEvent(
            kind=TOOL_CALL_FINISHED,
            run_id="run-1",
            payload={
                "tool_result": tool_result,
                "ok": True,
                "duration_s": 0.012,
            },
        ),
        AgentEvent(kind=TOOL_CALLS_FINISHED, run_id="run-1"),
    ]
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await _wait_until(lambda: bool(agent.turns))
    await agent.turns[0].waiting.wait()
    _emit_utterance(audio, vad)

    await audio.interrupted.wait()
    await asyncio.sleep(0)
    assert agent.prompts == ["查天气"]

    tool_finished.set()
    await _wait_until(lambda: len(agent.prompts) >= 2)

    assert agent.histories[1] == [
        {"role": "user", "content": "查天气"},
        tool_call,
        tool_result,
    ]

    await _cancel(task)


async def test_interruption_stops_waiting_for_a_stalled_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(turn_module, "_TOOL_COMPLETION_GRACE_SECONDS", 0.01)
    session, audio, vad, asr, agent, _tts, _log = _session()
    asr.transcripts.extend((Transcript("查天气"), Transcript("换个问题")))
    stalled = asyncio.Event()
    tool_call = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "weather", "arguments": "{}"},
            }
        ],
    }
    agent.next_events = [
        AgentEvent(
            kind=MODEL_RESPONSE_FINISHED,
            run_id="run-1",
            payload={"message": tool_call},
        ),
        AgentEvent(kind=TOOL_CALLS_STARTED, run_id="run-1"),
        stalled,
    ]
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await _wait_until(lambda: bool(agent.turns))
    await agent.turns[0].waiting.wait()
    _emit_utterance(audio, vad)

    await audio.interrupted.wait()
    await _wait_until(lambda: len(agent.prompts) >= 2)

    assert agent.turns[0].closed
    assert agent.histories[1] == [{"role": "user", "content": "查天气"}]

    await _cancel(task)


async def test_interruption_discards_tool_call_that_never_started() -> None:
    session, audio, vad, asr, agent, _tts, _log = _session()
    asr.transcripts.extend((Transcript("查天气"), Transcript("不用查了")))
    start_tool = asyncio.Event()
    tool_call = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "weather", "arguments": "{}"},
            }
        ],
    }
    agent.next_events = [
        AgentEvent(
            kind=MODEL_RESPONSE_FINISHED,
            run_id="run-1",
            payload={"message": tool_call},
        ),
        start_tool,
        AgentEvent(kind=TOOL_CALLS_STARTED, run_id="run-1"),
    ]
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await _wait_until(lambda: bool(agent.turns))
    await agent.turns[0].waiting.wait()
    _emit_utterance(audio, vad)

    await audio.interrupted.wait()
    await _wait_until(lambda: len(agent.prompts) >= 2)

    assert agent.histories[1] == [
        {"role": "user", "content": "查天气"},
    ]

    await _cancel(task)


async def test_interruption_preserves_tool_result_and_heard_followup() -> None:
    session, audio, vad, asr, agent, tts, _log = _session()
    asr.transcripts.extend((Transcript("查天气"), Transcript("继续")))
    tts.pause_after_parts = 1
    tool_call = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "weather", "arguments": "{}"},
            }
        ],
    }
    tool_result = {
        "role": "tool",
        "tool_call_id": "call-1",
        "name": "weather",
        "content": "晴天",
    }
    agent.next_events = [
        AgentEvent(
            kind=MODEL_RESPONSE_FINISHED,
            run_id="run-1",
            payload={"message": tool_call},
        ),
        AgentEvent(kind=TOOL_CALLS_STARTED, run_id="run-1"),
        AgentEvent(
            kind=TOOL_CALL_FINISHED,
            run_id="run-1",
            payload={
                "tool_result": tool_result,
                "ok": True,
                "duration_s": 0.012,
            },
        ),
        AgentEvent(kind=TOOL_CALLS_FINISHED, run_id="run-1"),
        AgentEvent(
            kind=MODEL_STREAM_CONTENT_DELTA,
            run_id="run-1",
            payload={"delta": "天气是晴天。后续内容"},
        ),
    ]
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await tts.text_marked.wait()
    _emit_utterance(audio, vad)

    await audio.interrupted.wait()
    await _wait_until(lambda: len(agent.prompts) >= 2)

    assert agent.histories[1] == [
        {"role": "user", "content": "查天气"},
        tool_call,
        tool_result,
        {"role": "assistant", "content": "天气是晴天。"},
    ]

    await _cancel(task)


async def test_empty_transcript_does_not_start_agent() -> None:
    session, audio, vad, asr, agent, _tts, _log = _session()
    asr.transcripts.append(Transcript(""))
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await asr.transcribed.wait()

    assert agent.prompts == []
    await _cancel(task)


async def test_tts_failure_ends_current_turn_and_continues_listening() -> None:
    events: list[VoiceEvent] = []
    session, audio, vad, asr, agent, tts, _log = _session(events)
    asr.transcripts.extend((Transcript("用户问题"), Transcript("再试一次")))
    tts.fail_synthesis = True
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await _wait_until(
        lambda: any(
            isinstance(event, ErrorEvent) and event.component is Component.TTS
            for event in events
        )
    )

    assert not task.done()
    assert session.history.get_history() == [
        {"role": "user", "content": "用户问题"},
    ]
    assert [event.state for event in events if isinstance(event, SynthesisEvent)] == [
        SynthesisState.STARTED,
        SynthesisState.FAILED,
    ]

    tts.fail_synthesis = False
    _emit_utterance(audio, vad)
    await _wait_until(lambda: len(agent.prompts) == 2)

    assert agent.histories[1] == [
        {"role": "user", "content": "用户问题"},
    ]
    await _cancel(task)


async def test_capture_error_propagates_and_closes_components() -> None:
    session, audio, _vad, _asr, _agent, _tts, log = _session()
    task = await _start(session, audio)
    error = RuntimeError("microphone failed")

    audio.emit(error)

    with pytest.raises(RuntimeError, match="microphone failed") as raised:
        await task
    assert raised.value is error
    assert log[-6:] == [
        "audio.close",
        "tts.close",
        "agent.close",
        "asr.close",
        "turn_detection.close",
        "vad.close",
    ]


async def test_start_failure_rolls_back_in_reverse_order() -> None:
    session, _audio, _vad, _asr, agent, _tts, log = _session()
    agent.fail_start = True

    with pytest.raises(RuntimeError, match="agent start failed"):
        await session.run()

    assert log == [
        "vad.start",
        "turn_detection.start",
        "asr.start",
        "agent.start",
        "agent.close",
        "asr.close",
        "turn_detection.close",
        "vad.close",
    ]


async def test_cancellation_closes_active_turn_and_synthesis() -> None:
    session, audio, vad, asr, agent, tts, _log = _session()
    asr.transcripts.append(Transcript("用户问题"))
    tts.release_audio.clear()
    task = await _start(session, audio)

    _emit_utterance(audio, vad)
    await tts.synthesis_started.wait()
    await _cancel(task)

    assert agent.turns[0].closed
    assert tts.streams[0].closed
    assert session.history.get_history() == []


async def test_rejects_output_format_mismatch() -> None:
    _session_value, audio, vad, asr, agent, tts, _log = _session()
    audio.output_format = AudioFormat(24_000)

    with pytest.raises(AudioFormatError, match="audio output"):
        VoiceSession(
            audio=audio,
            vad=vad,
            turn_analyzer=_FakeTurnAnalyzer([]),
            asr=asr,
            agent=cast(BumblehiveAgent, agent),
            tts=tts,
        )


async def test_session_can_only_run_once() -> None:
    session, audio, _vad, _asr, _agent, _tts, _log = _session()
    task = await _start(session, audio)
    await _cancel(task)

    with pytest.raises(RuntimeError, match="only be run once"):
        await session.run()
