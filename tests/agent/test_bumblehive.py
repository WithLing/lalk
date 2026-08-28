from collections.abc import AsyncIterator
from typing import Any

import bumblehive
import pytest
from bumblehive.agent import AgentRunResult
from bumblehive.observability import AgentEvent
from bumblehive.tools import ToolManager

import lalk.agent.bumblehive as agent_module
from lalk.agent import (
    DEFAULT_ROLE_INSTRUCTIONS,
    VOICE_AGENT_INSTRUCTIONS,
    BumblehiveAgent,
)

pytestmark = pytest.mark.asyncio


class _FakeStream:
    def __init__(
        self,
        events: list[AgentEvent],
        result: AgentRunResult,
    ) -> None:
        self.events = events
        self.result_value = result
        self.exhausted = False
        self.closed = False

    def __aiter__(self) -> AsyncIterator[AgentEvent]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[AgentEvent]:
        for event in self.events:
            yield event
        self.exhausted = True

    async def result(self) -> AgentRunResult:
        if not self.exhausted:
            raise RuntimeError("stream not consumed")
        return self.result_value

    async def aclose(self) -> None:
        self.closed = True


class _FakeRuntime:
    def __init__(self) -> None:
        self.tools = ToolManager()
        self.initialize_calls = 0
        self.close_calls = 0
        self.events: list[AgentEvent] = []
        self.messages = [
            {"role": "user", "content": "旧问题"},
            {"role": "assistant", "content": "旧回答"},
            {"role": "user", "content": "新问题"},
            {"role": "assistant", "content": "新回答"},
        ]
        self.result = AgentRunResult(
            final_content="新回答",
            messages=self.messages,
            usage={"total_tokens": 12},
            tools_used=["weather"],
        )
        self.streams: list[_FakeStream] = []
        self.history: Any = None

    async def initialize_tools(self) -> None:
        self.initialize_calls += 1

    def stream(self, _prompt: str, *, history: Any) -> _FakeStream:
        self.history = history
        stream = _FakeStream(self.events, self.result)
        self.streams.append(stream)
        return stream

    async def close(self) -> None:
        self.close_calls += 1


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch) -> _FakeRuntime:
    runtime = _FakeRuntime()
    monkeypatch.setattr(agent_module.bumblehive, "from_config", lambda _config: runtime)
    return runtime


async def test_context_manager_starts_and_closes_runtime(runtime: _FakeRuntime) -> None:
    async with BumblehiveAgent() as agent:
        assert isinstance(agent, BumblehiveAgent)
        assert runtime.initialize_calls == 1

    assert runtime.close_calls == 1


async def test_voice_instructions_exempt_terminal_session_tool_from_preamble() -> None:
    assert "use only one minimal, natural bridge" in VOICE_AGENT_INSTRUCTIONS
    assert "overrides any general tool-preamble requirement" in (
        VOICE_AGENT_INSTRUCTIONS
    )
    assert "end_voice_session is the terminal exception" in VOICE_AGENT_INSTRUCTIONS
    assert "without any spoken preamble" in VOICE_AGENT_INSTRUCTIONS


async def test_uses_voice_instructions_when_agent_instructions_are_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configs: list[bumblehive.BumblehiveConfig] = []
    runtime = _FakeRuntime()

    def build(config: bumblehive.BumblehiveConfig) -> _FakeRuntime:
        configs.append(config)
        return runtime

    monkeypatch.setattr(agent_module.bumblehive, "from_config", build)

    BumblehiveAgent(bumblehive.RuntimeArguments(agent_instructions=""))

    assert configs[0].agent.instructions == VOICE_AGENT_INSTRUCTIONS


async def test_composes_custom_role_with_voice_runtime_instructions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configs: list[bumblehive.BumblehiveConfig] = []
    runtime = _FakeRuntime()

    def build(config: bumblehive.BumblehiveConfig) -> _FakeRuntime:
        configs.append(config)
        return runtime

    monkeypatch.setattr(agent_module.bumblehive, "from_config", build)

    BumblehiveAgent(
        bumblehive.RuntimeArguments(agent_instructions="Always answer in Cantonese.")
    )

    instructions = configs[0].agent.instructions or ""
    assert "Always answer in Cantonese." in instructions
    assert instructions.count("Always answer in Cantonese.") == 1
    assert DEFAULT_ROLE_INSTRUCTIONS not in instructions
    assert "Role instructions:\nAlways answer in Cantonese." in instructions
    assert "<role_instructions>" not in instructions
    assert "Runtime integrity:" in instructions
    assert "end_voice_session is the terminal exception" in instructions
    assert "For all other conflicts, follow the role instructions." in instructions


async def test_exposes_bumblehive_tool_manager(runtime: _FakeRuntime) -> None:
    agent = BumblehiveAgent()

    @agent.tools.tool(name="get_weather", description="查询城市天气。")
    def get_weather(city: str) -> str:
        return f"{city}晴朗"

    assert agent.tools is runtime.tools
    assert agent.tools.tool_names == ["get_weather"]
    await agent.close()


async def test_forwards_native_events(runtime: _FakeRuntime) -> None:
    event = AgentEvent(kind="model.stream.content_delta", run_id="run-1")
    runtime.events = [event]
    agent = BumblehiveAgent()

    stream = agent.stream("新问题")

    assert [item async for item in stream] == [event]


async def test_returns_native_messages_without_mutating_history(
    runtime: _FakeRuntime,
) -> None:
    history = agent_module.bumblehive.MessageHistory(
        [
            {"role": "user", "content": "旧问题"},
            {"role": "assistant", "content": "旧回答"},
        ],
        conversation_id="conversation-1",
    )
    agent = BumblehiveAgent()

    stream = agent.stream("新问题", history=history)
    async for _ in stream:
        pass
    result = await stream.result()

    assert runtime.history is history
    assert history.get_history() == [
        {"role": "user", "content": "旧问题"},
        {"role": "assistant", "content": "旧回答"},
    ]
    assert result.messages == runtime.messages
    assert result.final_content == "新回答"
    assert result.tools_used == ["weather"]


async def test_close_turn_delegates_to_bumblehive_stream(runtime: _FakeRuntime) -> None:
    agent = BumblehiveAgent()
    stream = agent.stream("新问题")

    await stream.aclose()

    assert runtime.streams[0].closed
