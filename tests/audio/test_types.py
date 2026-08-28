import pytest

from lalk.audio import AudioChunk, AudioFormat, AudioFormatError


def test_audio_format_describes_pcm_frames() -> None:
    audio_format = AudioFormat(sample_rate=16_000, channels=1)
    chunk = AudioChunk(data=b"\x00\x00" * 320, format=audio_format)

    assert audio_format.frame_bytes == 2
    assert chunk.frame_count == 320
    assert chunk.duration_seconds == pytest.approx(0.02)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"sample_rate": 0}, "sample_rate"),
        ({"sample_rate": 16_000, "channels": 0}, "channels"),
    ],
)
def test_audio_format_rejects_invalid_values(
    kwargs: dict[str, int], message: str
) -> None:
    with pytest.raises(AudioFormatError, match=message):
        AudioFormat(**kwargs)


def test_audio_chunk_rejects_unaligned_pcm() -> None:
    with pytest.raises(AudioFormatError, match="not aligned"):
        AudioChunk(data=b"\x00", format=AudioFormat(16_000))


def test_audio_chunk_requires_bytes() -> None:
    with pytest.raises(AudioFormatError, match="must be bytes"):
        AudioChunk(data=bytearray(2), format=AudioFormat(16_000))  # type: ignore[arg-type]
