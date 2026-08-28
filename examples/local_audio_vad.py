"""Print speech state changes detected from the local microphone."""

import asyncio

from lalk.audio import LocalAudio
from lalk.vad import SileroVAD, VADState


async def main() -> None:
    audio = LocalAudio(input_sample_rate=16_000)
    vad = SileroVAD()

    try:
        await vad.start(audio.input_format)
        await audio.start()
        print("Listening... Press Ctrl+C to stop.")
        previous = VADState.SILENCE

        async for chunk in audio.capture():
            state = await vad.analyze(chunk)
            if state is previous:
                continue
            print("Speech started" if state is VADState.SPEAKING else "Speech ended")
            previous = state
    finally:
        await audio.close()
        await vad.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
