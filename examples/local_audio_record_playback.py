"""Record three seconds from the microphone, then play it back."""

import asyncio

from lalk.audio import AudioChunk, LocalAudio

RECORD_SECONDS = 3


async def main() -> None:
    audio = LocalAudio(
        input_sample_rate=48_000,
        output_sample_rate=48_000,
    )
    try:
        await audio.start()
        print(f"Recording for {RECORD_SECONDS} seconds...")
        blocks: list[bytes] = []
        recorded_frames = 0
        target_frames = audio.input_format.sample_rate * RECORD_SECONDS

        async for chunk in audio.capture():
            blocks.append(chunk.data)
            recorded_frames += chunk.frame_count
            if recorded_frames >= target_frames:
                break

        print("Playing...")
        recording = AudioChunk(
            data=b"".join(blocks),
            format=audio.output_format,
        )
        await audio.write(recording)
        await audio.wait_for_playback()
    finally:
        await audio.close()


if __name__ == "__main__":
    asyncio.run(main())
