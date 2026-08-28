"""Bumblehive runtime integration."""

from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Self

import bumblehive
from bumblehive.agent import AgentRunResult
from bumblehive.config import ConfigInput, load_config
from bumblehive.observability import AgentEvent, AsyncEventStream
from bumblehive.tools import ToolManager

from .instructions import compose_voice_agent_instructions


def _with_voice_instructions(
    config: ConfigInput,
) -> bumblehive.BumblehiveConfig:
    resolved = load_config(config)
    return replace(
        resolved,
        agent=replace(
            resolved.agent,
            instructions=compose_voice_agent_instructions(
                resolved.agent.instructions
            ),
        ),
    )


class AgentTurn:
    """Expose one native Bumblehive stream turn."""

    def __init__(
        self,
        stream: AsyncEventStream[AgentRunResult],
    ) -> None:
        self._stream = stream

    def __aiter__(self) -> AsyncIterator[AgentEvent]:
        return self._stream.__aiter__()

    async def result(self) -> AgentRunResult:
        """Return the native result for the session to commit."""

        return await self._stream.result()

    async def aclose(self) -> None:
        """Cancel unfinished work for this turn."""

        await self._stream.aclose()


class BumblehiveAgent:
    """Create streamed Bumblehive turns without committing history early."""

    def __init__(self, config: ConfigInput = None) -> None:
        self._runtime = bumblehive.from_config(
            _with_voice_instructions(config)
        )

    @property
    def tools(self) -> ToolManager:
        """Return the Bumblehive tool manager."""

        return self._runtime.tools

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.close()

    async def start(self) -> None:
        """Initialize Bumblehive tools and MCP connections."""

        await self._runtime.initialize_tools()

    def stream(
        self,
        prompt: str,
        *,
        history: bumblehive.MessageHistory | None = None,
    ) -> AgentTurn:
        """Start a turn using caller-managed read-only history."""

        stream = self._runtime.stream(prompt, history=history)
        return AgentTurn(stream)

    async def close(self) -> None:
        """Release Bumblehive resources."""

        await self._runtime.close()
