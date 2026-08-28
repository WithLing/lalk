"""Continuously transcribe VAD-delimited speech from the microphone."""

import asyncio

from _example_config import sensevoice_model_dir

from lalk.asr import SenseVoiceASR, SpeechSegmenter
from lalk.audio import LocalAudio
from lalk.vad import SileroVAD


async def main() -> None:
    audio = LocalAudio(input_sample_rate=16_000)
    vad = SileroVAD()
    asr = SenseVoiceASR(model_dir=sensevoice_model_dir())
    segmenter = SpeechSegmenter()

    try:
        await vad.start(audio.input_format)
        await asr.start(audio.input_format)
        await audio.start()

        print("Listening... Speak a sentence, then pause. Press Ctrl+C to stop.")
        async for chunk in audio.capture():
            state = await vad.analyze(chunk)
            segment = segmenter.push(chunk, state)
            if segment is None:
                continue

            stream = asr.recognize()
            await stream.write(segment)
            await stream.finish()
            transcripts = [transcript async for transcript in stream]
            text = "".join(transcript.text for transcript in transcripts)
            print(f"You: {text or '(no speech recognized)'}")
    finally:
        await audio.close()
        await vad.close()
        await asr.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
