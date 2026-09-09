"""Bumblehive runtime integration."""

import base64
import io
import wave
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Self

import bumblehive
from bumblehive.agent import AgentRunResult
from bumblehive.config import ConfigInput, load_config
from bumblehive.observability import AgentEvent, AsyncEventStream
from bumblehive.protocols import Message, UserMessage
from bumblehive.tools import ToolManager

from ..audio import AudioChunk
from .instructions import compose_voice_agent_instructions


def _with_voice_instructions(
    config: bumblehive.BumblehiveConfig,
) -> bumblehive.BumblehiveConfig:
    return replace(
        config,
        agent=replace(
            config.agent,
            instructions=compose_voice_agent_instructions(
                config.agent.instructions
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
        resolved = load_config(config)
        self._instructions_with_audio = compose_voice_agent_instructions(
            resolved.agent.instructions,
            send_audio_to_llm=True,
        )
        self._runtime = bumblehive.from_config(
            _with_voice_instructions(resolved)
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
        audio: AudioChunk | None = None,
        send_audio_to_llm: bool = False,
    ) -> AgentTurn:
        """Start a turn with optional audio and caller-managed read-only history."""

        if send_audio_to_llm:
            message: UserMessage = prompt
            if audio is not None:
                message = _audio_message(prompt, audio)
            stream = self._runtime.stream(
                message,
                history=history,
                config={"agent": {"instructions": self._instructions_with_audio}},
            )
        else:
            stream = self._runtime.stream(prompt, history=history)
        return AgentTurn(stream)

    async def close(self) -> None:
        """Release Bumblehive resources."""

        await self._runtime.close()


def _audio_message(prompt: str, audio: AudioChunk) -> list[Message]:
    """Encode one PCM utterance as a Chat Completions user message."""

    with io.BytesIO() as buffer:
        with wave.open(buffer, "wb") as wav:
            wav.setsampwidth(2)
            wav.setnchannels(audio.format.channels)
            wav.setframerate(audio.format.sample_rate)
            wav.writeframes(audio.data)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "input_audio",
                    "input_audio": {"data": encoded, "format": "wav"},
                },
            ],
        }
    ]
