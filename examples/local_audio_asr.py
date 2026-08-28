"""Record five seconds from the microphone and transcribe with SenseVoice."""

import asyncio

from _example_config import sensevoice_model_dir

from lalk.asr import SenseVoiceASR
from lalk.audio import AudioChunk, LocalAudio

RECORD_SECONDS = 5


async def main() -> None:
    audio = LocalAudio(input_sample_rate=16_000)
    asr = SenseVoiceASR(model_dir=sensevoice_model_dir())

    try:
        await asr.start(audio.input_format)
        await audio.start()

        print(f"Speak now. Recording for {RECORD_SECONDS} seconds...")
        blocks: list[bytes] = []
        recorded_frames = 0
        target_frames = audio.input_format.sample_rate * RECORD_SECONDS

        async for chunk in audio.capture():
            blocks.append(chunk.data)
            recorded_frames += chunk.frame_count
            if recorded_frames >= target_frames:
                break

        print("Transcribing...")
        recording = AudioChunk(
            data=b"".join(blocks),
            format=audio.input_format,
        )
        stream = asr.recognize()
        await stream.write(recording)
        await stream.finish()
        transcripts = [transcript async for transcript in stream]
        text = "".join(transcript.text for transcript in transcripts)
        print(f"Transcript: {text or '(no speech recognized)'}")
        if transcripts and transcripts[-1].language:
            print(f"Language: {transcripts[-1].language}")
        print(f"Usage: {await stream.result()}")
    finally:
        try:
            await audio.close()
        finally:
            await asr.close()


if __name__ == "__main__":
    asyncio.run(main())
