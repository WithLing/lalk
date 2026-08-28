import lalk
from lalk.audio import AudioChunk


def test_package_exposes_voice_session() -> None:
    assert AudioChunk is not None
    assert lalk.VoiceSession is not None
