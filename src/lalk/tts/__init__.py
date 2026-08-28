"""Text-to-speech interfaces and implementations."""

from .errors import TTSError, TTSStateError
from .protocols import TTS, TextInput, TTSOutput, TTSStream
from .text import TextSegmenter
from .types import TTSResult, TTSTextMark
from .volcengine import VolcengineTTS

__all__ = [
    "TTS",
    "TTSError",
    "TTSOutput",
    "TTSResult",
    "TTSStateError",
    "TTSStream",
    "TTSTextMark",
    "TextInput",
    "TextSegmenter",
    "VolcengineTTS",
]
