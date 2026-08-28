"""Local non-streaming SenseVoice speech recognition using sherpa-onnx."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Self

import numpy as np
import sherpa_onnx

from ..audio import AudioChunk, AudioFormat
from .errors import ASRError, ASRFormatError, ASRStateError
from .types import ASRResult, Transcript

_INPUT_FORMAT = AudioFormat(sample_rate=16_000, channels=1)
_SUPPORTED_LANGUAGES = ("auto", "zh", "en", "ja", "ko", "yue")


class _SenseVoiceStream:
    """Buffer one audio stream and recognize it when input finishes."""

    def __init__(self, asr: "SenseVoiceASR") -> None:
        self._asr = asr
        self._audio = bytearray()
        self._done = asyncio.Event()
        self._transcript: Transcript | None = None
        self._error: BaseException | None = None
        self._input_finished = False
        self._emitted = False
        self._closed = False
        self._result = ASRResult(0.0, 0, False)

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> Transcript:
        if self._closed or self._emitted:
            raise StopAsyncIteration
        try:
            await self._done.wait()
        except asyncio.CancelledError:
            await self.aclose()
            raise
        if self._error is not None:
            self._closed = True
            self._asr._release_stream(self)
            raise self._error
        transcript = self._transcript
        if transcript is None or not transcript.text:
            self._closed = True
            self._asr._release_stream(self)
            raise StopAsyncIteration
        self._emitted = True
        self._asr._release_stream(self)
        return transcript

    async def write(self, audio: AudioChunk) -> None:
        """Append one PCM chunk to this complete speech segment."""

        if self._closed or self._input_finished:
            raise ASRStateError("SenseVoice ASR input has already finished")
        if audio.format != self._asr.input_format:
            raise ASRFormatError(
                f"SenseVoiceASR requires {self._asr.input_format!r}, "
                f"received {audio.format!r}"
            )
        self._audio.extend(audio.data)

    async def finish(self) -> None:
        """Run one offline inference over all buffered PCM."""

        if self._closed or self._input_finished:
            return
        self._input_finished = True
        try:
            if self._audio:
                text, language = await self._asr._recognize(bytes(self._audio))
                self._transcript = Transcript(text=text, language=language)
            output_characters = (
                len(self._transcript.text) if self._transcript is not None else 0
            )
            self._result = ASRResult(
                input_audio_seconds=(
                    len(self._audio)
                    / self._asr.input_format.frame_bytes
                    / self._asr.input_format.sample_rate
                ),
                output_characters=output_characters,
                completed=True,
            )
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            self._error = error
            raise
        finally:
            self._done.set()

    async def aclose(self) -> None:
        """Discard buffered audio and release this stream."""

        if self._closed:
            return
        self._closed = True
        self._done.set()
        self._asr._release_stream(self)

    async def result(self) -> ASRResult:
        """Wait for recognition to finish and return measured usage."""

        await self._done.wait()
        if self._error is not None:
            raise self._error
        return self._result


class SenseVoiceASR:
    """Recognize complete 16 kHz mono PCM streams with SenseVoice."""

    @property
    def supports_interim_transcripts(self) -> bool:
        """SenseVoice recognizes only after the complete segment is submitted."""

        return False

    def __init__(
        self,
        *,
        model_dir: str | Path,
        threads: int = 4,
        language: str = "auto",
        use_itn: bool = True,
    ) -> None:
        """Store model settings without loading the recognizer."""

        if threads <= 0:
            raise ValueError("threads must be greater than zero")
        if language not in _SUPPORTED_LANGUAGES:
            supported = ", ".join(_SUPPORTED_LANGUAGES)
            raise ValueError(f"language must be one of: {supported}")

        self._model_dir = Path(model_dir).expanduser()
        self._threads = threads
        self._language = language
        self._use_itn = use_itn

        self._lock = asyncio.Lock()
        self._executor: ThreadPoolExecutor | None = None
        self._recognizer: Any | None = None
        self._input_format: AudioFormat | None = None
        self._stream: _SenseVoiceStream | None = None
        self._started = False
        self._closed = False

    @property
    def input_format(self) -> AudioFormat:
        """PCM format accepted by recognition streams."""

        return self._input_format or _INPUT_FORMAT

    async def start(self, input_format: AudioFormat) -> None:
        """Load the recognizer and validate its input format."""

        async with self._lock:
            if self._closed:
                raise ASRStateError("SenseVoiceASR has already been closed")
            if self._started:
                if input_format != self._input_format:
                    raise ASRStateError(
                        "SenseVoiceASR is already running with another audio format"
                    )
                return

            self._validate_format(input_format)
            model_path, tokens_path = self._resolve_model_files()

            executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="lalk-asr"
            )
            try:
                future = asyncio.get_running_loop().run_in_executor(
                    executor, self._load_model, model_path, tokens_path
                )
                recognizer = await self._await_worker(future)
            except asyncio.CancelledError:
                await asyncio.to_thread(
                    executor.shutdown, wait=True, cancel_futures=True
                )
                raise
            except Exception as error:
                await asyncio.to_thread(
                    executor.shutdown, wait=True, cancel_futures=True
                )
                raise ASRError(f"Unable to load SenseVoice model: {error}") from error

            self._executor = executor
            self._recognizer = recognizer
            self._input_format = input_format
            self._started = True

    def recognize(self) -> _SenseVoiceStream:
        """Create one buffered, non-streaming recognition task."""

        self._ensure_started()
        if self._stream is not None:
            raise ASRStateError("SenseVoiceASR supports one active stream at a time")
        stream = _SenseVoiceStream(self)
        self._stream = stream
        return stream

    async def close(self) -> None:
        """Release the active stream, recognizer, and inference thread."""

        async with self._lock:
            if self._closed:
                return
            self._closed = True
            self._started = False

            stream = self._stream
            if stream is not None:
                await stream.aclose()

            self._recognizer = None
            self._input_format = None
            executor = self._executor
            self._executor = None
            if executor is not None:
                await asyncio.to_thread(
                    executor.shutdown, wait=True, cancel_futures=True
                )

    async def _recognize(self, data: bytes) -> tuple[str, str | None]:
        executor = self._require_executor()
        try:
            future = asyncio.get_running_loop().run_in_executor(
                executor, self._transcribe_pcm, data
            )
            return await self._await_worker(future)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise ASRError(
                f"Unable to transcribe audio with SenseVoice: {error}"
            ) from error

    def _load_model(self, model_path: Path, tokens_path: Path) -> Any:
        return sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model_path),
            tokens=str(tokens_path),
            num_threads=self._threads,
            sample_rate=_INPUT_FORMAT.sample_rate,
            provider="cpu",
            language=self._language,
            use_itn=self._use_itn,
        )

    def _transcribe_pcm(self, data: bytes) -> tuple[str, str | None]:
        recognizer = self._require_recognizer()
        samples = np.frombuffer(data, dtype="<i2").astype(np.float32)
        samples *= 1.0 / 32_768.0

        stream = recognizer.create_stream()
        stream.accept_waveform(_INPUT_FORMAT.sample_rate, samples)
        recognizer.decode_stream(stream)
        result = stream.result
        return result.text.strip(), self._normalize_language(result.lang)

    @staticmethod
    def _normalize_language(language: str) -> str | None:
        language = language.strip()
        if language.startswith("<|") and language.endswith("|>"):
            language = language[2:-2]
        return language or None

    async def _await_worker(self, future: asyncio.Future[Any]) -> Any:
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            await asyncio.shield(future)
            raise

    def _validate_format(self, input_format: AudioFormat) -> None:
        if input_format != _INPUT_FORMAT:
            raise ASRFormatError(
                f"SenseVoiceASR requires {_INPUT_FORMAT!r}, received {input_format!r}"
            )

    def _resolve_model_files(self) -> tuple[Path, Path]:
        if not self._model_dir.is_dir():
            raise ASRError(
                f"SenseVoice model directory does not exist: {self._model_dir}"
            )

        model_paths = sorted(
            path for path in self._model_dir.glob("*.onnx") if path.is_file()
        )
        if len(model_paths) != 1:
            raise ASRError(
                "SenseVoice model directory must contain exactly one ONNX model: "
                f"{self._model_dir}"
            )

        tokens_path = self._model_dir / "tokens.txt"
        if not tokens_path.is_file():
            raise ASRError(f"SenseVoice tokens file does not exist: {tokens_path}")

        return model_paths[0], tokens_path

    def _ensure_started(self) -> None:
        if self._closed:
            raise ASRStateError("SenseVoiceASR has been closed")
        if not self._started:
            raise ASRStateError("SenseVoiceASR has not been started")

    def _require_executor(self) -> ThreadPoolExecutor:
        if self._executor is None:
            raise ASRStateError("SenseVoiceASR inference worker is unavailable")
        return self._executor

    def _require_recognizer(self) -> Any:
        if self._recognizer is None:
            raise ASRStateError("SenseVoiceASR model is unavailable")
        return self._recognizer

    def _release_stream(self, stream: _SenseVoiceStream) -> None:
        if self._stream is stream:
            self._stream = None
