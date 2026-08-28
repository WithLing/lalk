import asyncio
import json
import logging
import struct
from collections.abc import AsyncIterator
from typing import Any

import pytest

import lalk.tts.volcengine as tts_module
from lalk.audio import AudioChunk, AudioFormat
from lalk.tts import (
    TTS,
    TTSError,
    TTSOutput,
    TTSResult,
    TTSStateError,
    TTSStream,
    TTSTextMark,
    VolcengineTTS,
)
from lalk.tts._vendor.volcengine import EventType, MsgType, MsgTypeFlagBits
from lalk.tts._vendor.volcengine import receive_message as vendor_receive_message

pytestmark = pytest.mark.asyncio


def _server_message(
    message_type: MsgType,
    event: EventType | int,
    *,
    session_id: str = "",
    payload: bytes = b"",
) -> bytes:
    data = bytearray((0x11, (message_type << 4) | MsgTypeFlagBits.WithEvent, 0x10, 0))
    if message_type == MsgType.Error:
        data.extend(struct.pack(">I", 500))
    data.extend(struct.pack(">i", event))
    identifier = (
        b"connection"
        if event
        in {
            EventType.ConnectionStarted,
            EventType.ConnectionFailed,
            EventType.ConnectionFinished,
        }
        else session_id.encode()
    )
    data.extend(struct.pack(">I", len(identifier)))
    data.extend(identifier)
    data.extend(struct.pack(">I", len(payload)))
    data.extend(payload)
    return bytes(data)


def _client_event(message: bytes) -> EventType:
    return EventType(struct.unpack(">i", message[4:8])[0])


def _client_session_id(message: bytes) -> str:
    size = struct.unpack(">I", message[8:12])[0]
    return message[12 : 12 + size].decode()


def _client_payload(message: bytes) -> bytes:
    event = _client_event(message)
    offset = 8
    if event not in {EventType.StartConnection, EventType.FinishConnection}:
        size = struct.unpack(">I", message[offset : offset + 4])[0]
        offset += 4 + size
    size = struct.unpack(">I", message[offset : offset + 4])[0]
    return message[offset + 4 : offset + 4 + size]


class _FakeWebSocket:
    def __init__(self) -> None:
        self.incoming: asyncio.Queue[bytes | str] = asyncio.Queue()
        self.sent: list[bytes] = []
        self.closed = False
        self.task_requested = asyncio.Event()
        self.audio_on_task_request = False
        self.audio_payloads = [b"\x01\x00" * 320]
        self.finish_payload = b'{"usage":{"text_words":2}}'
        self.subtitle_payloads: list[bytes] = []
        self.sentence_text = "你好。"
        self.fail_session = False
        self.invalid_cancel_response = False
        self.invalid_finish_response = False
        self.connect_kwargs: dict[str, Any] = {}

    async def send(self, message: bytes) -> None:
        self.sent.append(message)
        event = _client_event(message)

        if event == EventType.StartConnection:
            self.incoming.put_nowait(
                _server_message(MsgType.FullServerResponse, EventType.ConnectionStarted)
            )
        elif event == EventType.StartSession:
            session_id = _client_session_id(message)
            if self.fail_session:
                self.incoming.put_nowait(
                    _server_message(
                        MsgType.FullServerResponse,
                        EventType.SessionFailed,
                        session_id=session_id,
                        payload=b"invalid voice",
                    )
                )
            else:
                self.incoming.put_nowait(
                    _server_message(
                        MsgType.FullServerResponse,
                        EventType.SessionStarted,
                        session_id=session_id,
                    )
                )
        elif event == EventType.TaskRequest:
            self.task_requested.set()
            if self.audio_on_task_request:
                for payload in self.audio_payloads:
                    self.incoming.put_nowait(
                        _server_message(
                            MsgType.AudioOnlyServer,
                            EventType.TTSResponse,
                            session_id=_client_session_id(message),
                            payload=payload,
                        )
                    )
        elif event == EventType.FinishSession:
            session_id = _client_session_id(message)
            if self.subtitle_payloads:
                self.incoming.put_nowait(
                    _server_message(
                        MsgType.FullServerResponse,
                        EventType.TTSSentenceStart,
                        session_id=session_id,
                    )
                )
            if not self.audio_on_task_request:
                for payload in self.audio_payloads:
                    self.incoming.put_nowait(
                        _server_message(
                            MsgType.AudioOnlyServer,
                            EventType.TTSResponse,
                            session_id=session_id,
                            payload=payload,
                        )
                    )
            if self.subtitle_payloads:
                self.incoming.put_nowait(
                    _server_message(
                        MsgType.FullServerResponse,
                        EventType.TTSSentenceEnd,
                        session_id=session_id,
                        payload=json.dumps(
                            {"text": self.sentence_text},
                            ensure_ascii=False,
                        ).encode(),
                    )
                )
                for payload in self.subtitle_payloads:
                    self.incoming.put_nowait(
                        _server_message(
                            MsgType.FullServerResponse,
                            EventType.TTSSubtitle,
                            session_id=session_id,
                            payload=payload,
                        )
                    )
            self.incoming.put_nowait(
                _server_message(
                    MsgType.FullServerResponse,
                    EventType.SessionFinished,
                    session_id=session_id,
                    payload=self.finish_payload,
                )
            )
        elif event == EventType.CancelSession:
            if self.invalid_cancel_response:
                self.incoming.put_nowait("invalid cancel response")
            else:
                self.incoming.put_nowait(
                    _server_message(
                        MsgType.FullServerResponse,
                        EventType.SessionCanceled,
                        session_id=_client_session_id(message),
                    )
                )
        elif event == EventType.FinishConnection:
            response = (
                "invalid finish response"
                if self.invalid_finish_response
                else _server_message(
                    MsgType.FullServerResponse, EventType.ConnectionFinished
                )
            )
            self.incoming.put_nowait(response)

    async def recv(self) -> str | bytes:
        return await self.incoming.get()

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_websocket(monkeypatch: pytest.MonkeyPatch) -> _FakeWebSocket:
    websocket = _FakeWebSocket()

    async def connect(*_args: Any, **_kwargs: Any) -> _FakeWebSocket:
        websocket.connect_kwargs = _kwargs
        return websocket

    monkeypatch.setattr(tts_module.websockets, "connect", connect)
    return websocket


def _tts() -> VolcengineTTS:
    return VolcengineTTS(api_key="api-key")


async def test_implements_tts_protocol(fake_websocket: _FakeWebSocket) -> None:
    tts: TTS = _tts()

    await tts.start()
    stream = tts.synthesize("你好")
    chunks = [chunk async for chunk in stream]
    result = await stream.result()
    await tts.close()

    assert chunks == [AudioChunk(b"\x01\x00" * 320, AudioFormat(48_000))]
    assert result == TTSResult(
        input_characters=2,
        audio_bytes=640,
        completed=True,
        provider_usage={"text_words": 2},
    )
    assert fake_websocket.closed

    headers = fake_websocket.connect_kwargs["additional_headers"]
    assert headers["X-Api-Key"] == "api-key"
    assert "X-Api-App-Id" not in headers
    assert "X-Api-App-Key" not in headers
    assert "X-Api-Access-Key" not in headers
    assert headers["X-Control-Require-Usage-Tokens-Return"] == "*"


async def test_connection_uses_bundled_ca(
    fake_websocket: _FakeWebSocket,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ssl_context = object()
    cafiles: list[str] = []

    monkeypatch.setattr(tts_module.certifi, "where", lambda: "/bundle/cacert.pem")

    def create_default_context(*, cafile: str) -> object:
        cafiles.append(cafile)
        return ssl_context

    monkeypatch.setattr(
        tts_module.ssl,
        "create_default_context",
        create_default_context,
    )

    tts = _tts()
    await tts.start()
    await tts.close()

    assert cafiles == ["/bundle/cacert.pem"]
    assert fake_websocket.connect_kwargs["ssl"] is ssl_context


async def test_rejects_empty_api_key() -> None:
    with pytest.raises(ValueError, match="api_key"):
        VolcengineTTS(api_key=" ")


async def test_rejects_unsupported_sample_rate() -> None:
    with pytest.raises(ValueError, match="sample_rate must be one of"):
        VolcengineTTS(api_key="api-key", sample_rate=12_345)


async def test_sends_streamed_text_in_one_session(
    fake_websocket: _FakeWebSocket,
) -> None:
    async def text() -> AsyncIterator[str]:
        yield "第一句。"
        yield " "
        yield " 第二句。"

    tts = _tts()
    await tts.start()
    stream = tts.synthesize(text())
    chunks = [chunk async for chunk in stream]
    result = await stream.result()
    await tts.close()

    requests = [
        json.loads(_client_payload(message))
        for message in fake_websocket.sent
        if _client_event(message) == EventType.TaskRequest
    ]
    session_ids = {
        _client_session_id(message)
        for message in fake_websocket.sent
        if _client_event(message)
        in {EventType.StartSession, EventType.TaskRequest, EventType.FinishSession}
    }

    assert [request["req_params"]["text"] for request in requests] == [
        "第一句。",
        " 第二句。",
    ]
    assert len(session_ids) == 1
    assert chunks[0].format == tts.output_format
    assert result.input_characters == len("第一句。 第二句。")
    assert requests[0]["req_params"]["audio_params"]["enable_subtitle"] is True


async def test_emits_word_marks_from_provider_subtitles(
    fake_websocket: _FakeWebSocket,
) -> None:
    fake_websocket.subtitle_payloads = [
        json.dumps(
            {
                "text": "你好，Lalk。",
                "words": [
                    {"word": "你", "startTime": 0.001, "endTime": 0.002},
                    {"word": "好，", "startTime": 0.002, "endTime": 0.003},
                    {
                        "word": "Lalk。",
                        "startTime": 0.004,
                        "endTime": 0.006,
                    },
                ],
            },
            ensure_ascii=False,
        ).encode()
    ]
    fake_websocket.sentence_text = "你好，Lalk。"
    tts = _tts()
    await tts.start()

    outputs = [output async for output in tts.synthesize("你好，Lalk。")]
    await tts.close()

    assert outputs == [
        AudioChunk(b"\x01\x00" * 320, AudioFormat(48_000)),
        TTSTextMark("你", 48),
        TTSTextMark("好", 96),
        TTSTextMark("，", 120),
        TTSTextMark("L", 192),
        TTSTextMark("a", 211),
        TTSTextMark("l", 230),
        TTSTextMark("k", 250),
        TTSTextMark("。", 269),
    ]


async def test_supports_separate_subtitles_with_session_relative_timestamps(
    fake_websocket: _FakeWebSocket,
) -> None:
    fake_websocket.subtitle_payloads = [
        json.dumps(
            {
                "text": "第一句。",
                "words": [{"word": "第一句。", "startTime": 0.001, "endTime": 0.003}],
            },
            ensure_ascii=False,
        ).encode(),
        json.dumps(
            {
                "text": "第二句。",
                "words": [{"word": "第二句。", "startTime": 0.004, "endTime": 0.006}],
            },
            ensure_ascii=False,
        ).encode(),
    ]
    fake_websocket.sentence_text = "第一句。第二句。"
    tts = _tts()
    await tts.start()

    outputs = [output async for output in tts.synthesize("第一句。第二句。")]
    await tts.close()

    assert outputs == [
        AudioChunk(b"\x01\x00" * 320, AudioFormat(48_000)),
        TTSTextMark("第", 48),
        TTSTextMark("一", 72),
        TTSTextMark("句", 96),
        TTSTextMark("。", 120),
        TTSTextMark("第", 192),
        TTSTextMark("二", 216),
        TTSTextMark("句", 240),
        TTSTextMark("。", 264),
    ]


async def test_offsets_sentence_timestamps_by_accumulated_audio() -> None:
    tts = _tts()
    subtitle = tts._parse_subtitle(
        json.dumps(
            {
                "text": "第二句。",
                "words": [
                    {
                        "word": "第二句。",
                        "startTime": 0.1,
                        "endTime": 0.3,
                    }
                ],
            },
            ensure_ascii=False,
        ).encode()
    )

    assert subtitle is not None
    assert tts._subtitle_marks(
        subtitle,
        audio_start_frame=48_000,
    ) == [
        TTSTextMark("第", 52_800),
        TTSTextMark("二", 55_200),
        TTSTextMark("句", 57_600),
        TTSTextMark("。", 60_000),
    ]


async def test_ignores_duplicate_subtitle_marks(
    fake_websocket: _FakeWebSocket,
) -> None:
    subtitle = json.dumps(
        {
            "text": "你好。",
            "words": [{"word": "你好。", "startTime": 0.001, "endTime": 0.003}],
        },
        ensure_ascii=False,
    ).encode()
    fake_websocket.subtitle_payloads = [subtitle, subtitle]
    tts = _tts()
    await tts.start()

    outputs = [output async for output in tts.synthesize("你好。")]
    await tts.close()

    assert outputs == [
        AudioChunk(b"\x01\x00" * 320, AudioFormat(48_000)),
        TTSTextMark("你", 48),
        TTSTextMark("好", 80),
        TTSTextMark("。", 112),
    ]


async def test_uses_sentence_end_as_conservative_text_mark(
    fake_websocket: _FakeWebSocket,
) -> None:
    fake_websocket.subtitle_payloads = [b"invalid subtitle"]
    tts = _tts()
    await tts.start()

    outputs = [output async for output in tts.synthesize("你好。")]
    await tts.close()

    assert outputs == [
        AudioChunk(b"\x01\x00" * 320, AudioFormat(48_000)),
        TTSTextMark("你好。", 320),
    ]


async def test_yields_audio_before_text_stream_finishes(
    fake_websocket: _FakeWebSocket,
) -> None:
    release_text = asyncio.Event()
    fake_websocket.audio_on_task_request = True

    async def text() -> AsyncIterator[str]:
        yield "第一句。"
        await release_text.wait()
        yield "第二句。"

    tts = _tts()
    await tts.start()
    stream = tts.synthesize(text())

    first_chunk = await anext(stream)
    assert first_chunk.data == b"\x01\x00" * 320

    release_text.set()
    remaining = [chunk async for chunk in stream]
    await tts.close()
    assert len(remaining) == 1


async def test_canceling_consumer_cancels_provider_session(
    fake_websocket: _FakeWebSocket,
) -> None:
    never = asyncio.Event()

    async def text() -> AsyncIterator[str]:
        yield "正在说话。"
        await never.wait()

    tts = _tts()
    await tts.start()
    consumer = asyncio.ensure_future(anext(tts.synthesize(text())))
    await asyncio.wait_for(fake_websocket.task_requested.wait(), 1)

    consumer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consumer
    await tts.close()

    events = [_client_event(message) for message in fake_websocket.sent]
    assert EventType.CancelSession in events
    assert EventType.FinishSession not in events


async def test_breaking_stream_then_closing_cancels_provider_session(
    fake_websocket: _FakeWebSocket,
) -> None:
    never = asyncio.Event()
    fake_websocket.audio_on_task_request = True

    async def text() -> AsyncIterator[str]:
        yield "正在说话。"
        await never.wait()

    tts = _tts()
    await tts.start()
    stream = tts.synthesize(text())

    async for chunk in stream:
        assert chunk.data == b"\x01\x00" * 320
        break

    await asyncio.wait_for(tts.close(), 1)
    result = await stream.result()

    events = [_client_event(message) for message in fake_websocket.sent]
    assert EventType.CancelSession in events
    assert fake_websocket.closed
    assert result == TTSResult(
        input_characters=len("正在说话。"),
        audio_bytes=640,
        completed=False,
        provider_usage=None,
    )


async def test_close_does_not_cancel_consumer_task(
    fake_websocket: _FakeWebSocket,
) -> None:
    never = asyncio.Event()
    fake_websocket.audio_on_task_request = True

    async def text() -> AsyncIterator[str]:
        yield "正在说话。"
        await never.wait()

    tts = _tts()
    await tts.start()
    consumer = asyncio.create_task(
        _collect(tts.synthesize(text())),
        name="tts-consumer",
    )
    await asyncio.wait_for(fake_websocket.task_requested.wait(), 1)

    await tts.close()
    await asyncio.wait_for(consumer, 1)

    assert not consumer.cancelled()
    assert fake_websocket.closed


async def test_aligns_pcm_across_provider_messages(
    fake_websocket: _FakeWebSocket,
) -> None:
    fake_websocket.audio_payloads = [b"\x01", b"\x00\x02"]
    tts = _tts()
    await tts.start()

    chunks = [chunk async for chunk in tts.synthesize("你好")]
    await tts.close()

    assert [chunk.data for chunk in chunks] == [b"\x01\x00", b"\x02\x00"]


async def test_invalid_provider_usage_does_not_fail_synthesis(
    fake_websocket: _FakeWebSocket,
) -> None:
    fake_websocket.finish_payload = b"not-json"
    tts = _tts()
    await tts.start()
    stream = tts.synthesize("你好")

    chunks = [chunk async for chunk in stream]
    result = await stream.result()
    await tts.close()

    assert chunks
    assert result.completed
    assert result.provider_usage is None


async def test_cleanup_does_not_mask_synthesis_error(
    fake_websocket: _FakeWebSocket,
) -> None:
    fake_websocket.invalid_cancel_response = True

    async def text() -> AsyncIterator[str]:
        yield "第一句。"
        raise RuntimeError("text stream failed")

    tts = _tts()
    await tts.start()

    with pytest.raises(TTSError, match="text stream failed"):
        async for _ in tts.synthesize(text()):
            pass

    await tts.close()
    assert fake_websocket.closed


async def test_close_ignores_invalid_provider_response(
    fake_websocket: _FakeWebSocket,
) -> None:
    fake_websocket.invalid_finish_response = True
    tts = _tts()
    await tts.start()

    await tts.close()

    assert fake_websocket.closed


async def test_provider_errors_are_raised(fake_websocket: _FakeWebSocket) -> None:
    fake_websocket.fail_session = True
    tts = _tts()
    await tts.start()

    with pytest.raises(TTSError, match="invalid voice"):
        async for _ in tts.synthesize("你好"):
            pass

    await tts.close()


async def test_lifecycle_state_errors(fake_websocket: _FakeWebSocket) -> None:
    tts = _tts()

    with pytest.raises(TTSStateError, match="not been started"):
        await anext(tts.synthesize("你好"))

    await tts.start()
    await tts.close()
    await tts.close()

    with pytest.raises(TTSStateError, match="closed"):
        await tts.start()


async def _collect(stream: TTSStream) -> list[TTSOutput]:
    return [output async for output in stream]


async def test_vendor_logging_defaults_to_warning() -> None:
    assert logging.getLogger(vendor_receive_message.__module__).level == logging.WARNING
