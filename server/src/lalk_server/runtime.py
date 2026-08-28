"""Single-session Lalk runtime."""

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import bumblehive

from lalk import ConversationInactivityPolicy, InactivityAction, VoiceSession
from lalk.agent import BumblehiveAgent
from lalk.asr import QwenAudioASR
from lalk.audio import LocalAudio
from lalk.observability import (
    ErrorEvent,
    MetricsEvent,
    SessionEvent,
    SessionState,
    VoiceEvent,
    VoiceObserver,
)
from lalk.tts import VolcengineTTS
from lalk.turn_detection import SmartTurnV3
from lalk.vad import AdaptiveInputLevelGate, SileroVAD

from .config import AppConfig, load_config, save_config
from .history import ConversationHistory, load_history, save_history
from .proactive import (
    ProactiveNotFoundError,
    ProactiveService,
    ProactiveStateError,
    register_proactive_tools,
)
from .protocol import RuntimeView

SessionBuilder = Callable[
    [AppConfig, VoiceObserver, bumblehive.MessageHistory, ProactiveService],
    VoiceSession,
]


class CommandError(Exception):
    """Expected command rejection returned to the desktop client."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def build_session(
    config: AppConfig,
    observer: VoiceObserver,
    history: bumblehive.MessageHistory,
    proactive: ProactiveService,
) -> VoiceSession:
    """Construct the concrete Lalk session described by the config."""

    tts_settings = config.tts.settings
    tts = VolcengineTTS(
        api_key=tts_settings.api_key,
        voice=tts_settings.voice,
        resource_id=tts_settings.resource_id,
        sample_rate=tts_settings.sample_rate,
    )
    audio_config = config.audio
    vad_config = config.vad
    turn_detection_config = config.turn_detection
    interruption_config = config.interruption
    asr_settings = config.asr.settings
    inactivity_config = config.inactivity_policy
    agent_config = bumblehive.BumblehiveConfig.from_mapping(config.bumblehive)
    if agent_config.agent.tool_names is not None:
        agent_config = replace(
            agent_config,
            agent=replace(
                agent_config.agent,
                tool_names=tuple(
                    dict.fromkeys(
                        (
                            *agent_config.agent.tool_names,
                            "schedule_proactive",
                            "cancel_proactive",
                            "end_voice_session",
                        )
                    )
                ),
            ),
        )
    agent = BumblehiveAgent(agent_config)
    register_proactive_tools(agent, proactive)

    session = VoiceSession(
        audio=LocalAudio(
            input_device=audio_config.input_device,
            output_device=audio_config.output_device,
            input_sample_rate=16_000,
            output_sample_rate=tts.output_format.sample_rate,
            block_ms=audio_config.block_ms,
            capture_buffer_ms=audio_config.capture_buffer_ms,
            latency=audio_config.latency,
            echo_cancellation=audio_config.echo_cancellation,
        ),
        vad=SileroVAD(
            threshold=vad_config.threshold,
            min_input_level=(
                0.0 if vad_config.adaptive_input_level else vad_config.min_input_level
            ),
            speech_start_ms=vad_config.speech_start_ms,
            speech_end_ms=vad_config.speech_end_ms,
        ),
        turn_analyzer=SmartTurnV3(),
        incomplete_turn_timeout_seconds=(
            turn_detection_config.incomplete_timeout_ms / 1_000
        ),
        backchannel_filter_enabled=(
            interruption_config.backchannel_filter_enabled
        ),
        backchannel_phrases=interruption_config.backchannel_phrases,
        asr=QwenAudioASR(
            api_key=asr_settings.api_key,
            workspace_id=asr_settings.workspace_id,
        ),
        agent=agent,
        tts=tts,
        history=history,
        observers=[observer],
        opening_enabled=config.opening_enabled,
        input_level_gate=(
            AdaptiveInputLevelGate(minimum_level=vad_config.min_input_level)
            if vad_config.adaptive_input_level
            else None
        ),
        inactivity_policy=(
            ConversationInactivityPolicy(
                timeout_seconds=inactivity_config.timeout_seconds,
                max_followups=inactivity_config.max_followups,
                on_exhausted=InactivityAction(inactivity_config.on_exhausted),
            )
            if inactivity_config is not None
            else None
        ),
    )
    register_session_tools(agent, session)
    return session


def register_session_tools(
    agent: BumblehiveAgent,
    session: VoiceSession,
) -> None:
    """Register the voice-session control available to the agent."""

    @agent.tools.tool(
        name="end_voice_session",
        description=(
            "用于结束当前语音会话。以下任一情况满足时必须调用："
            "（1）用户明确要求停止继续说话、关闭语音或结束当前会话；"
            "（2）当前 Agent 指令定义了明确的会话目标和完成条件，且这些"
            "条件已经得到确认，必要的确认、总结或下一步说明也已经完成。"
            "若用户意图仍然模糊、目标只完成一部分、仍有必要信息或问题未处理，"
            "或者用户只是打断当前回答并继续交流，则不要调用。这是终止型工具："
            "调用前不要输出承接语、确认语或结束语，直接调用工具。工具成功后只"
            "回复一句符合当前场景的简短自然结束语，不再提问、重复告别或开启"
            "新内容。当前回复播放完成后关闭语音，但不会退出桌面应用或影响后台提醒。"
        ),
    )
    async def end_voice_session() -> dict[str, bool]:
        session.request_stop_after_turn()
        return {"ending": True}


def _with_default_workspace(config: AppConfig, workspace: Path) -> AppConfig:
    bumblehive_config = dict(config.bumblehive)
    runtime_config = dict(bumblehive_config.get("runtime") or {})
    if not runtime_config.get("workspace"):
        runtime_config["workspace"] = str(workspace)
    bumblehive_config["runtime"] = runtime_config
    return config.model_copy(update={"bumblehive": bumblehive_config})


class RuntimeController:
    """Own one local VoiceSession, configuration, and conversation history."""

    def __init__(
        self,
        config_path: Path,
        *,
        session_builder: SessionBuilder = build_session,
    ) -> None:
        self._config_path = config_path
        self._history_path = config_path.parent / "history.json"
        self._default_workspace = config_path.parent / "workspace"
        self._session_builder = session_builder
        self._lock = asyncio.Lock()
        self._session: VoiceSession | None = None
        self._session_task: asyncio.Task[None] | None = None
        self._config: AppConfig | None = None
        self._config_error: str | None = None

        try:
            self._config = load_config(config_path)
        except (OSError, ValueError, TypeError) as error:
            self._config_error = str(error)

        stored_history = load_history(self._history_path)
        if stored_history is None:
            self._message_history = bumblehive.MessageHistory()
            turns = None
        else:
            self._message_history = bumblehive.MessageHistory(
                stored_history.messages,
                conversation_id=stored_history.conversation_id,
            )
            turns = stored_history.turns

        state = "idle" if self._config is not None else "unconfigured"
        self.view = RuntimeView(state, turns=turns)
        self.proactive = ProactiveService(
            config_path.parent / "proactive.json",
            self.view.set_proactive_offer,
        )
        self._session_ready = asyncio.Event()

    async def start_background(self) -> None:
        """Start services that must outlive individual voice sessions."""

        await self.proactive.start()

    async def close(self) -> None:
        """Stop background services and the active voice session."""

        await self.proactive.close()
        await self.stop()

    def config_response(self) -> dict[str, object]:
        return {
            "config": (
                self._config.model_dump(mode="json")
                if self._config is not None
                else None
            ),
            "error": self._config_error,
        }

    async def update_config(self, incoming: AppConfig) -> dict[str, object]:
        async with self._lock:
            if self._session_task is not None:
                raise CommandError(
                    "session_active",
                    "Configuration cannot change while the session is active",
                )
            await save_config(self._config_path, incoming)
            self._config = incoming
            self._config_error = None
            self.view.set_runtime_state("idle")
            return self.config_response()

    async def start(self) -> str:
        return await self._start_session()

    async def _start_session(self, *, skip_opening: bool = False) -> str:
        async with self._lock:
            if self._session_task is not None:
                raise CommandError("session_active", "A session is already active")
            if self._config is None:
                raise CommandError("config_missing", "Server configuration is missing")

            try:
                session_config = _with_default_workspace(
                    self._config,
                    self._default_workspace,
                )
                if skip_opening:
                    session_config = session_config.model_copy(
                        update={"opening_enabled": False}
                    )
                session = self._session_builder(
                    session_config,
                    self,
                    self._message_history,
                    self.proactive,
                )
            except Exception as error:
                self.view.set_runtime_state(
                    "failed",
                    error={"type": type(error).__name__, "message": str(error)},
                )
                raise

            self._session = session
            self._session_ready.clear()
            self.view.set_runtime_state("starting")
            self._session_task = asyncio.create_task(
                self._run_session(session),
                name="lalk-server-session",
            )
            return session.session_id

    async def stop(self) -> bool:
        async with self._lock:
            session = self._session
            task = self._session_task
            if session is None or task is None:
                return False
            self.view.set_runtime_state("stopping")

        try:
            await session.stop()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        finally:
            try:
                await self._save_history()
            finally:
                async with self._lock:
                    if self._session is session:
                        self._session = None
                        self._session_task = None
                        self._session_ready.clear()
                        if self.view.runtime_state != "failed":
                            self.view.set_runtime_state("idle")
        return True

    async def on_event(self, event: VoiceEvent) -> None:
        """Update the desktop projection and persist completed turn state."""

        self.view.on_event(event)
        if isinstance(event, SessionEvent) and event.state is SessionState.READY:
            self._session_ready.set()
        if isinstance(event, MetricsEvent) or (
            isinstance(event, ErrorEvent) and event.turn_id is not None
        ):
            await self._save_history()

    async def new_conversation(self) -> str:
        """End voice activity and replace the current conversation."""

        await self.stop()
        async with self._lock:
            self._message_history = bumblehive.MessageHistory()
            self.view.new_conversation()
            await self._save_history()
            return self._message_history.conversation_id

    def interrupt(self) -> bool:
        session = self._running_session()
        return session.interrupt()

    def submit_text(self, text: str) -> None:
        session = self._running_session()
        try:
            session.submit_text(text)
        except asyncio.QueueFull as error:
            raise CommandError(
                "input_busy",
                "Another input is already queued",
            ) from error
        except ValueError as error:
            raise CommandError("invalid_text", str(error)) from error
        except RuntimeError as error:
            raise CommandError("session_not_ready", str(error)) from error

    async def answer_proactive(self, request_id: str) -> str:
        """Accept an offer and start its hidden agent-initiated turn."""

        try:
            request = await self.proactive.get_offered(request_id)
        except (ProactiveNotFoundError, ProactiveStateError) as error:
            raise CommandError("proactive_stale", str(error)) from error

        task = self._session_task
        if task is None:
            await self._start_session(skip_opening=True)
            task = self._session_task
        if task is None:
            raise CommandError("session_not_running", "No session is running")

        if self.view.runtime_state == "starting":
            await self._wait_until_ready(task)
        if self.view.runtime_state != "running" or self.view.stage != "listening":
            raise CommandError(
                "session_busy",
                "Wait for the current voice turn to finish before answering",
            )

        session = self._running_session()
        try:
            session.submit_proactive(request.instruction)
        except asyncio.QueueFull as error:
            raise CommandError(
                "session_busy",
                "Another input is already queued",
            ) from error
        except RuntimeError as error:
            code = (
                "session_busy"
                if str(error) == "VoiceSession is busy"
                else "session_not_ready"
            )
            raise CommandError(code, str(error)) from error
        await self.proactive.remove(request.id)
        return session.session_id

    async def dismiss_proactive(self, request_id: str) -> None:
        """Dismiss the currently offered request."""

        try:
            await self.proactive.get_offered(request_id)
            await self.proactive.remove(request_id)
        except (ProactiveNotFoundError, ProactiveStateError) as error:
            raise CommandError("proactive_stale", str(error)) from error

    async def snooze_proactive(self, request_id: str, minutes: int) -> None:
        """Delay the currently offered request by a small user-selected interval."""

        try:
            await self.proactive.snooze(
                request_id,
                datetime.now(UTC) + timedelta(minutes=minutes),
            )
        except (ProactiveNotFoundError, ProactiveStateError) as error:
            raise CommandError("proactive_stale", str(error)) from error

    async def _run_session(self, session: VoiceSession) -> None:
        try:
            await session.run()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if self.view.runtime_state != "failed":
                self.view.set_runtime_state(
                    "failed",
                    error={"type": type(error).__name__, "message": str(error)},
                )
        finally:
            async with self._lock:
                if self._session is session:
                    self._session = None
                    self._session_task = None
                    self._session_ready.clear()
                    if self.view.runtime_state != "failed":
                        self.view.set_runtime_state("idle")

    def _running_session(self) -> VoiceSession:
        session = self._session
        if session is None or self._session_task is None:
            raise CommandError("session_not_running", "No session is running")
        return session

    async def _wait_until_ready(self, session_task: asyncio.Task[None]) -> None:
        ready = asyncio.create_task(
            self._session_ready.wait(),
            name="lalk-wait-session-ready",
        )
        done, _ = await asyncio.wait(
            {ready, session_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if ready in done:
            return
        ready.cancel()
        await asyncio.gather(ready, return_exceptions=True)
        await asyncio.gather(session_task, return_exceptions=True)
        raise CommandError("session_start_failed", "The voice session did not start")

    async def _save_history(self) -> None:
        await save_history(
            self._history_path,
            ConversationHistory(
                conversation_id=self._message_history.conversation_id,
                messages=self._message_history.get_history(),
                turns=self.view.persisted_turns(),
            ),
        )
