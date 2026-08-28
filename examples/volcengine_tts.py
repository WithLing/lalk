"""Play one sentence synthesized by Volcengine TTS."""

import asyncio
import os

from _example_config import required_env

from lalk.audio import AudioChunk, LocalAudio
from lalk.tts import VolcengineTTS


async def main() -> None:
    tts = VolcengineTTS(
        api_key=required_env("VOLCENGINE_API_KEY"),
        voice=os.getenv("VOLCENGINE_SPEAKER", "zh_female_vv_uranus_bigtts"),
        resource_id=os.getenv("VOLCENGINE_RESOURCE_ID", "seed-tts-2.0"),
    )
    audio = LocalAudio(output_sample_rate=tts.output_format.sample_rate)

    try:
        await tts.start()
        await audio.start()
        stream = tts.synthesize("你好，我是 Lalk。")
        try:
            async for output in stream:
                if isinstance(output, AudioChunk):
                    await audio.write(output)
            await audio.wait_for_playback()
            print(f"Usage: {await stream.result()}")
        finally:
            await stream.aclose()
    finally:
        await audio.close()
        await tts.close()


if __name__ == "__main__":
    asyncio.run(main())
