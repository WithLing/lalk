"""Stream microphone audio to Volcengine ASR and print live transcripts."""

import asyncio

from _example_config import required_env

from lalk.asr import VolcengineASR
from lalk.audio import LocalAudio


async def main() -> None:
    audio = LocalAudio(input_sample_rate=16_000, input_channels=1)
    asr = VolcengineASR(
        api_key=required_env("VOLCENGINE_API_KEY"),
    )

    try:
        await asr.start(audio.input_format)
        await audio.start()
        stream = asr.recognize()

        async def send_audio() -> None:
            async for chunk in audio.capture():
                await stream.write(chunk)

        async def print_transcripts() -> None:
            async for transcript in stream:
                kind = "final" if transcript.is_final else "interim"
                print(f"[{kind}] {transcript.text}", flush=True)

        try:
            print("Listening with Volcengine... Press Ctrl+C to stop.")
            await asyncio.gather(send_audio(), print_transcripts())
        finally:
            await stream.aclose()
    finally:
        await audio.close()
        await asr.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
