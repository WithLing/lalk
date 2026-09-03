"""Stream one Bumblehive response through Volcengine TTS and local speakers."""

import asyncio
import os
from collections.abc import AsyncIterator

import bumblehive
from _example_config import required_env
from bumblehive.observability import (
    MODEL_STREAM_CONTENT_DELTA,
    MODEL_STREAM_REFUSAL_DELTA,
)

from lalk.agent import (
    VOICE_AGENT_INSTRUCTIONS,
    AgentTurn,
    BumblehiveAgent,
)
from lalk.audio import AudioChunk, LocalAudio
from lalk.tts import StreamingTextProcessor, VolcengineTTS

_TEXT_EVENTS = (MODEL_STREAM_CONTENT_DELTA, MODEL_STREAM_REFUSAL_DELTA)


async def response_text(turn: AgentTurn) -> AsyncIterator[str]:
    processor = StreamingTextProcessor(
        normalize_markdown=True,
        first_chunk_chars=6,
        chunk_chars=24,
    )

    async for event in turn:
        if event.kind not in _TEXT_EVENTS:
            continue

        delta = event.payload.get("delta")
        if not isinstance(delta, str):
            continue
        print(delta, end="", flush=True)
        for text in processor.push(delta):
            yield text

    for text in processor.flush():
        yield text


async def main() -> None:
    agent = BumblehiveAgent(
        bumblehive.RuntimeArguments(
            model=os.getenv("BUMBLEHIVE_MODEL", "deepseek-chat"),
            api_key=required_env("BUMBLEHIVE_API_KEY"),
            base_url=os.getenv("BUMBLEHIVE_BASE_URL", "https://api.deepseek.com"),
            agent_instructions=VOICE_AGENT_INSTRUCTIONS,
        )
    )
    tts = VolcengineTTS(
        api_key=required_env("VOLCENGINE_API_KEY"),
        voice=os.getenv("VOLCENGINE_SPEAKER", "zh_female_vv_uranus_bigtts"),
        resource_id=os.getenv("VOLCENGINE_RESOURCE_ID", "seed-tts-2.0"),
    )
    audio = LocalAudio(output_sample_rate=tts.output_format.sample_rate)

    try:
        await agent.start()
        await tts.start()
        await audio.start()

        turn = agent.stream("用两句话介绍你自己。")
        speech = tts.synthesize(response_text(turn))
        try:
            print("Assistant: ", end="", flush=True)
            async for output in speech:
                if isinstance(output, AudioChunk):
                    await audio.write(output)

            await audio.wait_for_playback()
            agent_result = await turn.result()
            tts_result = await speech.result()
            print(f"\nAgent usage: {agent_result.usage}")
            print(f"TTS usage: {tts_result.provider_usage}")
        finally:
            await speech.aclose()
            await turn.aclose()
    finally:
        await audio.close()
        await tts.close()
        await agent.close()


if __name__ == "__main__":
    asyncio.run(main())
