import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import bumblehive
import pytest
from bumblehive.protocols import ToolCall
from bumblehive.tools import ToolManager
from lalk_server.config import AppConfig, save_config
from lalk_server.history import ConversationHistory, load_history, save_history
from lalk_server.proactive import ProactiveService
from lalk_server.runtime import (
    CommandError,
    RuntimeController,
    SessionBuilder,
    register_session_tools,
)

from lalk.observability import (
    AgentTextEvent,
    InputSource,
    MetricsEvent,
    PlaybackEvent,
    PlaybackState,
    SessionEvent,
    SessionState,
    TurnEvent,
    TurnMetrics,
    TurnState,
    UserInputEvent,
    VoiceObserver,
)


class FakeSession:
    def __init__(
        self,
        observer: VoiceObserver,
        history: bumblehive.MessageHistory,
        *,
        session_id: str = "fake-session",
    ) -> None:
        self.session_id = session_id
        self._observer = observer
        self.history = history
        self._stop = asyncio.Event()
        self.interrupt_result = True
        self.texts: list[str] = []
        self.proactive_inputs: list[str] = []
        self.actions: list[str] = []

    async def run(self) -> None:
        self.actions.append("run")
        await self._emit(
            SessionEvent(session_id=self.session_id, state=SessionState.STARTING)
        )
        await self._emit(
            SessionEvent(session_id=self.session_id, state=SessionState.READY)
        )
        await self._stop.wait()
        await self._emit(
            SessionEvent(session_id=self.session_id, state=SessionState.STOPPING)
        )
        await self._emit(
            SessionEvent(session_id=self.session_id, state=SessionState.STOPPED)
        )

    async def stop(self) -> None:
        self._stop.set()

    def interrupt(self) -> bool:
        return self.interrupt_result

    def submit_text(self, text: str) -> None:
        if not text.strip():
            raise ValueError("Text input must not be empty")
        self.texts.append(text)

    def submit_proactive(self, instruction: str) -> None:
        self.proactive_inputs.append(instruction)
        self.actions.append("proactive")

    async def _emit(self, event: SessionEvent) -> None:
        result = self._observer.on_event(event)
        if result is not None:
            await result


class FakeSessionControl:
    def __init__(self) -> None:
        self.stop_requested = False

    def request_stop_after_turn(self) -> None:
        self.stop_requested = True


@pytest.mark.asyncio
async def test_end_voice_session_tool_requests_graceful_session_stop() -> None:
    agent: Any = SimpleNamespace(tools=ToolManager())
    session: Any = FakeSessionControl()
    register_session_tools(agent, session)

    result = await agent.tools.execute_call(
        ToolCall(id="call-1", name="end_voice_session", arguments={})
    )

    assert result.content == {"ending": True}
    assert session.stop_requested is True
    tool = agent.tools.get_tool("end_voice_session")
    assert tool is not None
    assert "会话目标和完成条件" in tool.description
    assert "调用前不要输出承接语" in tool.description
    assert "工具成功后只回复" in tool.description
    assert "简短自然结束语" in tool.description
    assert "不再提问、重复告别" in tool.description
    assert "目标只完成一部分" in tool.description
    assert tool.parameters == {
        "additionalProperties": False,
        "properties": {},
        "type": "object",
    }


async def wait_for_proactive_offer(runtime: RuntimeController) -> None:
    queue = runtime.view.subscribe()
    try:
        snapshot = queue.get_nowait()
        if snapshot["data"]["proactive_offer"] is not None:
            return
        async with asyncio.timeout(1):
            while True:
                message = await queue.get()
                if message["type"] == "proactive.offer":
                    return
    finally:
        runtime.view.unsubscribe(queue)


@pytest.mark.asyncio
async def test_controller_runs_exactly_one_session(
    tmp_path: Path,
    app_config: AppConfig,
) -> None:
    config_path = tmp_path / "config.json"
    await save_config(config_path, app_config)
    built: list[FakeSession] = []

    def builder(
        _config: AppConfig,
        observer: VoiceObserver,
        history: bumblehive.MessageHistory,
        _proactive: ProactiveService,
    ) -> Any:
        session = FakeSession(observer, history)
        built.append(session)
        return session

    runtime = RuntimeController(config_path, session_builder=builder)

    assert await runtime.start() == "fake-session"
    await asyncio.sleep(0)
    assert runtime.view.runtime_state == "running"
    with pytest.raises(CommandError, match="already active"):
        await runtime.start()

    runtime.submit_text("hello")
    assert runtime.interrupt() is True
    assert built[0].texts == ["hello"]
    assert await runtime.stop() is True
    assert runtime.view.runtime_state == "idle"
    assert await runtime.stop() is False


@pytest.mark.asyncio
async def test_controller_uses_lalk_workspace_by_default(
    tmp_path: Path,
    app_config: AppConfig,
) -> None:
    config_path = tmp_path / "config.json"
    await save_config(config_path, app_config)
    built_configs: list[AppConfig] = []

    def builder(
        config: AppConfig,
        observer: VoiceObserver,
        history: bumblehive.MessageHistory,
        _proactive: ProactiveService,
    ) -> Any:
        built_configs.append(config)
        return FakeSession(observer, history)

    runtime = RuntimeController(config_path, session_builder=builder)

    await runtime.start()
    assert built_configs[0].bumblehive["runtime"]["workspace"] == str(
        tmp_path / "workspace"
    )
    stored_config = runtime.config_response()["config"]
    assert isinstance(stored_config, dict)
    assert "runtime" not in stored_config["bumblehive"]
    await runtime.stop()


@pytest.mark.asyncio
async def test_controller_preserves_configured_workspace(
    tmp_path: Path,
    config_data: dict[str, Any],
) -> None:
    configured_workspace = tmp_path / "custom-workspace"
    config_data["bumblehive"]["runtime"] = {"workspace": str(configured_workspace)}
    app_config = AppConfig.model_validate(config_data)
    config_path = tmp_path / "config.json"
    await save_config(config_path, app_config)
    built_configs: list[AppConfig] = []

    def builder(
        config: AppConfig,
        observer: VoiceObserver,
        history: bumblehive.MessageHistory,
        _proactive: ProactiveService,
    ) -> Any:
        built_configs.append(config)
        return FakeSession(observer, history)

    runtime = RuntimeController(config_path, session_builder=builder)

    await runtime.start()
    assert built_configs[0].bumblehive["runtime"]["workspace"] == str(
        configured_workspace
    )
    await runtime.stop()


@pytest.mark.asyncio
async def test_config_cannot_change_during_session(
    tmp_path: Path,
    app_config: AppConfig,
) -> None:
    path = tmp_path / "config.json"
    await save_config(path, app_config)
    runtime = RuntimeController(
        path,
        session_builder=cast(
            SessionBuilder,
            lambda _config, observer, history, _proactive: FakeSession(
                observer,
                history,
            ),
        ),
    )

    await runtime.start()
    with pytest.raises(CommandError, match="cannot change"):
        await runtime.update_config(app_config)
    await runtime.stop()


def test_invalid_stored_config_keeps_server_unconfigured(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("not json", encoding="utf-8")

    runtime = RuntimeController(path)

    response = runtime.config_response()
    assert runtime.view.runtime_state == "unconfigured"
    assert response["config"] is None
    assert response["error"] is not None


def test_config_response_includes_api_keys(
    tmp_path: Path,
    app_config: AppConfig,
) -> None:
    path = tmp_path / "config.json"
    path.write_text(app_config.model_dump_json(), encoding="utf-8")

    config = RuntimeController(path).config_response()["config"]

    assert isinstance(config, dict)
    assert config["tts"]["settings"]["api_key"] == "tts-secret"
    assert config["bumblehive"]["provider"]["api_key"] == "agent-secret"


@pytest.mark.asyncio
async def test_controller_restores_agent_and_frontend_history(
    tmp_path: Path,
    app_config: AppConfig,
) -> None:
    config_path = tmp_path / "config.json"
    await save_config(config_path, app_config)
    histories: list[bumblehive.MessageHistory] = []

    def builder(
        _config: AppConfig,
        observer: VoiceObserver,
        history: bumblehive.MessageHistory,
        _proactive: ProactiveService,
    ) -> Any:
        histories.append(history)
        return FakeSession(observer, history, session_id=f"session-{len(histories)}")

    runtime = RuntimeController(config_path, session_builder=builder)
    assert await runtime.start() == "session-1"
    await asyncio.sleep(0)

    histories[0].replace(
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
    )
    await runtime.on_event(
        UserInputEvent(
            session_id="session-1",
            turn_id=1,
            source=InputSource.TEXT,
            text="hello",
        )
    )
    await runtime.on_event(
        TurnEvent(session_id="session-1", turn_id=1, state=TurnState.STARTED)
    )
    await runtime.on_event(
        AgentTextEvent(session_id="session-1", turn_id=1, delta="hi")
    )
    await runtime.on_event(
        PlaybackEvent(
            session_id="session-1",
            turn_id=1,
            state=PlaybackState.FINISHED,
            spoken_text="hi",
        )
    )
    await runtime.on_event(
        TurnEvent(session_id="session-1", turn_id=1, state=TurnState.COMPLETED)
    )
    await runtime.on_event(
        MetricsEvent(
            session_id="session-1",
            turn_id=1,
            metrics=TurnMetrics(turn_ms=10.0),
        )
    )
    await runtime.stop()

    stored = load_history(tmp_path / "history.json")
    assert stored is not None
    assert stored.messages == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    assert stored.turns[0]["session_id"] == "session-1"
    assert stored.turns[0]["assistant"]["playback_state"] == "finished"

    restored_histories: list[bumblehive.MessageHistory] = []

    def restored_builder(
        _config: AppConfig,
        observer: VoiceObserver,
        history: bumblehive.MessageHistory,
        _proactive: ProactiveService,
    ) -> Any:
        restored_histories.append(history)
        return FakeSession(observer, history, session_id="session-2")

    restored = RuntimeController(config_path, session_builder=restored_builder)
    assert restored.view.snapshot()["turns"] == stored.turns
    assert await restored.start() == "session-2"
    assert restored_histories[0].conversation_id == stored.conversation_id
    assert restored_histories[0].get_history() == stored.messages
    await restored.stop()


@pytest.mark.asyncio
async def test_new_conversation_replaces_history_and_stops_active_voice(
    tmp_path: Path,
    app_config: AppConfig,
) -> None:
    config_path = tmp_path / "config.json"
    history_path = tmp_path / "history.json"
    await save_config(config_path, app_config)
    await save_history(
        history_path,
        ConversationHistory(
            conversation_id="conversation-1",
            messages=[{"role": "user", "content": "old"}],
            turns=[
                {
                    "session_id": "old-session",
                    "turn_id": 1,
                    "state": "completed",
                }
            ],
        ),
    )
    histories: list[bumblehive.MessageHistory] = []

    def builder(
        _config: AppConfig,
        observer: VoiceObserver,
        history: bumblehive.MessageHistory,
        _proactive: ProactiveService,
    ) -> Any:
        histories.append(history)
        return FakeSession(observer, history)

    runtime = RuntimeController(config_path, session_builder=builder)

    old_conversation_id = "conversation-1"
    await runtime.start()
    await asyncio.sleep(0)

    new_conversation_id = await runtime.new_conversation()

    assert new_conversation_id != old_conversation_id
    assert runtime.view.runtime_state == "idle"
    assert runtime.view.snapshot()["turns"] == []
    stored = load_history(history_path)
    assert stored is not None
    assert stored.conversation_id == new_conversation_id
    assert stored.messages == []
    assert stored.turns == []

    await runtime.start()
    assert histories[-1].conversation_id == new_conversation_id
    assert histories[-1].get_history() == []
    await runtime.stop()


@pytest.mark.asyncio
async def test_answer_proactive_starts_idle_session_without_text_interrupt(
    tmp_path: Path,
    app_config: AppConfig,
) -> None:
    config_path = tmp_path / "config.json"
    await save_config(
        config_path,
        app_config.model_copy(update={"opening_enabled": True}),
    )
    sessions: list[FakeSession] = []
    session_configs: list[AppConfig] = []

    def builder(
        config: AppConfig,
        observer: VoiceObserver,
        history: bumblehive.MessageHistory,
        _proactive: ProactiveService,
    ) -> Any:
        session_configs.append(config)
        session = FakeSession(observer, history)
        sessions.append(session)
        return session

    runtime = RuntimeController(config_path, session_builder=builder)
    await runtime.start_background()
    request = await runtime.proactive.enqueue(
        title="开会",
        instruction="提醒用户参加产品会议。",
        available_at=datetime.now(UTC),
    )
    await wait_for_proactive_offer(runtime)

    session_id = await runtime.answer_proactive(request.id)

    assert session_id == "fake-session"
    assert sessions[0].texts == []
    assert sessions[0].proactive_inputs == ["提醒用户参加产品会议。"]
    assert sessions[0].actions == ["run", "proactive"]
    assert session_configs[0].opening_enabled is False
    stored_config = runtime.config_response()["config"]
    assert isinstance(stored_config, dict)
    assert stored_config["opening_enabled"] is True
    assert runtime.view.proactive_offer is None
    await runtime.close()


@pytest.mark.asyncio
async def test_answer_proactive_is_rejected_while_turn_is_busy(
    tmp_path: Path,
    app_config: AppConfig,
) -> None:
    config_path = tmp_path / "config.json"
    await save_config(config_path, app_config)

    def builder(
        _config: AppConfig,
        observer: VoiceObserver,
        history: bumblehive.MessageHistory,
        _proactive: ProactiveService,
    ) -> Any:
        return FakeSession(observer, history)

    runtime = RuntimeController(config_path, session_builder=builder)
    await runtime.start_background()
    await runtime.start()
    await asyncio.sleep(0)
    await runtime.on_event(
        UserInputEvent(
            session_id="fake-session",
            turn_id=1,
            source=InputSource.VOICE,
            text="还在说话",
        )
    )
    await runtime.on_event(
        TurnEvent(
            session_id="fake-session",
            turn_id=1,
            state=TurnState.STARTED,
        )
    )
    request = await runtime.proactive.enqueue(
        title="稍后提醒",
        instruction="提醒用户。",
        available_at=datetime.now(UTC),
    )
    await wait_for_proactive_offer(runtime)

    with pytest.raises(CommandError) as rejected:
        await runtime.answer_proactive(request.id)

    assert rejected.value.code == "session_busy"
    assert runtime.view.proactive_offer is not None
    await runtime.close()
