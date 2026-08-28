import pytest

from lalk.audio._level import pcm16_rms_level


def test_pcm16_rms_level_uses_normalized_sample_amplitude() -> None:
    assert pcm16_rms_level(b"") == 0.0
    assert pcm16_rms_level(b"\x00\x00" * 4) == 0.0
    assert pcm16_rms_level(b"\x00\x40\x00\xc0") == pytest.approx(0.5)
