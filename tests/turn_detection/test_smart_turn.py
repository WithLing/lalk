import pytest

from lalk.audio import AudioChunk, AudioFormat
from lalk.turn_detection import (
    SmartTurnV3,
    TurnDetectionFormatError,
    TurnDetectionStateError,
)

pytestmark = pytest.mark.asyncio

_FORMAT = AudioFormat(16_000)


async def test_runs_the_bundled_smart_turn_model() -> None:
    analyzer = SmartTurnV3()
    await analyzer.start(_FORMAT)
    try:
        result = await analyzer.analyze(AudioChunk(bytes(16_000 * 2), _FORMAT))
    finally:
        await analyzer.close()

    assert 0.0 <= result.probability <= 1.0

    with pytest.raises(TurnDetectionStateError, match="closed"):
        await analyzer.analyze(AudioChunk(b"", _FORMAT))


async def test_rejects_non_model_audio_format() -> None:
    analyzer = SmartTurnV3()

    with pytest.raises(TurnDetectionFormatError, match="16000"):
        await analyzer.start(AudioFormat(48_000))
