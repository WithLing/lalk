import asyncio
import gzip
import json
import struct

import pytest

import lalk.asr.volcengine as module
from lalk.asr import ASRError, ASRFormatError, ASRStateError, Transcript, VolcengineASR
from lalk.audio import AudioChunk, AudioFormat


def response(text=None, final=False, last=False, compressed=False):
    payload = {"result": {}}
    if text is not None:
        payload["result"]["utterances"] = [{"text": text, "definite": final}]
    body = json.dumps(payload).encode()
    if compressed:
        body = gzip.compress(body)
    # The real server's last frame had a positive sequence with flags=3.
    return (
        bytes((0x11, 0x93 if last else 0x91, 0x11 if compressed else 0x10, 0))
        + struct.pack(">iI", 8, len(body))
        + body
    )


class Socket:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.sent = []
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def send(self, frame):
        self.sent.append(frame)
        if frame[1] & 2:
            for item in [
                response(),
                response("你好"),
                response("你好"),
                response("你好", final=True),
                response("你好", final=True, last=True, compressed=True),
            ]:
                await self.incoming.put(item)

    async def recv(self):
        return await self.incoming.get()


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [0, 3198, 3200, 3202, 6400, 6402])
async def test_stream_finish_and_repeat_sentences(monkeypatch, size):
    sockets = []

    def connect(url, **kwargs):
        assert set(kwargs["additional_headers"]) == {
            "X-Api-Key",
            "X-Api-Resource-Id",
            "X-Api-Request-Id",
        }
        socket = Socket()
        sockets.append(socket)
        return socket

    monkeypatch.setattr(module.websockets, "connect", connect)
    async with VolcengineASR(api_key="test") as asr:
        stream = asr.recognize()
        await stream.write(AudioChunk(bytes(size), asr.input_format))
        await stream.finish()
        assert [t async for t in stream] == [
            Transcript("你好", False),
            Transcript("你好"),
            Transcript("你好"),
        ]
        result = await stream.result()
        assert result.completed
        assert result.output_characters == 4
        assert result.input_audio_seconds == size / 32000
        assert result.provider_usage is None
        socket = sockets[0]
        assert socket.closed
        assert socket.sent[-1][1] == 0x22
        assert [len(gzip.decompress(f[8:])) for f in socket.sent[1:]] == (
            [3200] * (size // 3200) + [size % 3200]
        )
        assert b"".join(gzip.decompress(f[8:]) for f in socket.sent[1:]) == bytes(size)
        request = json.loads(gzip.decompress(socket.sent[0][8:]))
        assert request["request"]["result_type"] == "single"
        next_stream = asr.recognize()
        await next_stream.aclose()
        assert not (await next_stream.result()).completed


@pytest.mark.asyncio
async def test_cancel_and_state(monkeypatch):
    socket = Socket()
    monkeypatch.setattr(module.websockets, "connect", lambda *a, **k: socket)
    asr = VolcengineASR(api_key="test")
    with pytest.raises(ASRStateError):
        asr.recognize()
    with pytest.raises(ASRFormatError):
        await asr.start(AudioFormat(8000))
    await asr.start(AudioFormat(16000))
    stream = asr.recognize()
    with pytest.raises(ASRStateError):
        asr.recognize()
    with pytest.raises(ASRFormatError):
        await stream.write(AudioChunk(b"00", AudioFormat(8000)))
    await asyncio.sleep(0)
    await asr.close()
    assert socket.closed
    assert not (await stream.result()).completed


@pytest.mark.asyncio
async def test_server_error_reaches_consumer_and_finish(monkeypatch):
    socket = Socket()
    body = b'{"error":"invalid request"}'
    socket.incoming.put_nowait(
        bytes((0x11, 0xF0, 0x10, 0)) + struct.pack(">II", 45000081, len(body)) + body
    )
    monkeypatch.setattr(module.websockets, "connect", lambda *a, **k: socket)
    async with VolcengineASR(api_key="test") as asr:
        stream = asr.recognize()
        with pytest.raises(ASRError, match="45000081"):
            await stream.finish()
        with pytest.raises(ASRError, match="45000081"):
            await anext(stream)
        assert socket.closed


@pytest.mark.asyncio
async def test_finish_timeout(monkeypatch):
    socket = Socket()

    async def send(frame):
        socket.sent.append(frame)

    socket.send = send
    monkeypatch.setattr(module.websockets, "connect", lambda *a, **k: socket)
    monkeypatch.setattr(module, "_FINISH_TIMEOUT", 0.01)
    async with VolcengineASR(api_key="test") as asr:
        stream = asr.recognize()
        with pytest.raises(ASRError):
            await stream.finish()
        assert socket.closed
