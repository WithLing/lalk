import struct

import pytest

from lalk.tts._vendor.volcengine import (
    EventType,
    Message,
    MsgType,
    MsgTypeFlagBits,
)


def test_marshals_client_session_event() -> None:
    message = Message(
        type=MsgType.FullClientRequest,
        flag=MsgTypeFlagBits.WithEvent,
        event=EventType.StartSession,
        session_id="session-1",
        payload=b'{"hello":true}',
    )

    data = message.marshal()

    assert data[:4] == bytes((0x11, 0x14, 0x10, 0))
    assert struct.unpack(">i", data[4:8])[0] == EventType.StartSession
    assert b"session-1" in data
    assert data.endswith(b'{"hello":true}')


def test_unmarshals_server_audio_event() -> None:
    source = Message(
        type=MsgType.AudioOnlyServer,
        flag=MsgTypeFlagBits.WithEvent,
        event=EventType.TTSResponse,
        session_id="session-1",
        payload=b"\x01\x00\x02\x00",
    )

    message = Message.from_bytes(source.marshal())

    assert message.type == MsgType.AudioOnlyServer
    assert message.event == EventType.TTSResponse
    assert message.session_id == "session-1"
    assert message.payload == b"\x01\x00\x02\x00"


@pytest.mark.parametrize("data", [b"", b"\x11", b"\x11\x94"])
def test_rejects_incomplete_messages(data: bytes) -> None:
    with pytest.raises(ValueError):
        Message.from_bytes(data)
