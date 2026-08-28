from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient
from lalk_server.app import _resolve_config_path, create_app
from lalk_server.protocol import RuntimeView
from lalk_server.runtime import RuntimeController
from starlette.websockets import WebSocketDisconnect


class StubController:
    def __init__(self) -> None:
        self.view = RuntimeView("idle")
        self.stopped = False
        self.new_conversation_requested = False
        self.texts: list[str] = []
        self.proactive_actions: list[tuple[object, ...]] = []

    async def start_background(self) -> None:
        pass

    async def close(self) -> None:
        await self.stop()

    def config_response(self) -> dict[str, object]:
        return {"config": None, "error": None}

    async def stop(self) -> bool:
        self.stopped = True
        return True

    async def start(self) -> str:
        return "session-1"

    def interrupt(self) -> bool:
        return False

    def submit_text(self, text: str) -> None:
        self.texts.append(text)

    async def new_conversation(self) -> str:
        self.new_conversation_requested = True
        return "conversation-2"

    async def answer_proactive(self, request_id: str) -> str:
        self.proactive_actions.append(("answer", request_id))
        return "session-1"

    async def dismiss_proactive(self, request_id: str) -> None:
        self.proactive_actions.append(("dismiss", request_id))

    async def snooze_proactive(self, request_id: str, minutes: int) -> None:
        self.proactive_actions.append(("snooze", request_id, minutes))


def test_resolve_config_path() -> None:
    assert _resolve_config_path(None) == (Path.home() / ".lalk" / "config.json")
    assert _resolve_config_path(Path("~/custom.json")) == (Path.home() / "custom.json")


def test_create_app_uses_default_config_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[Path] = []

    def create_controller(path: Path) -> StubController:
        captured.append(path)
        return StubController()

    monkeypatch.setattr("lalk_server.app.RuntimeController", create_controller)

    with TestClient(create_app()):
        pass

    assert captured == [Path.home() / ".lalk" / "config.json"]


def test_health_and_websocket_commands(tmp_path: Path) -> None:
    controller = StubController()
    app = create_app(
        config_path=tmp_path / "config.json",
        controller=cast(RuntimeController, controller),
    )

    with TestClient(app) as client:
        assert client.get("/health").json() == {
            "status": "ok",
            "runtime_state": "idle",
        }
        with client.websocket_connect("/ws") as websocket:
            assert websocket.receive_json()["type"] == "snapshot"
            websocket.send_json({"id": "0", "type": "conversation.new"})
            assert websocket.receive_json() == {
                "type": "command.result",
                "id": "0",
                "ok": True,
                "data": {"conversation_id": "conversation-2"},
            }
            assert controller.new_conversation_requested is True
            websocket.send_json({"id": "1", "type": "session.start"})
            assert websocket.receive_json() == {
                "type": "command.result",
                "id": "1",
                "ok": True,
                "data": {"session_id": "session-1"},
            }
            websocket.send_json(
                {"id": "2", "type": "turn.submit_text", "text": "hello"}
            )
            assert websocket.receive_json()["ok"] is True
            assert controller.texts == ["hello"]
            websocket.send_json(
                {
                    "id": "3",
                    "type": "proactive.snooze",
                    "request_id": "request-1",
                    "minutes": 10,
                }
            )
            assert websocket.receive_json()["ok"] is True
            assert controller.proactive_actions == [("snooze", "request-1", 10)]

    assert controller.stopped is True


def test_model_list_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[tuple[str, str]] = []

    async def fetch_models(base_url: str, api_key: str) -> list[str]:
        requests.append((base_url, api_key))
        return ["model-a", "model-b"]

    monkeypatch.setattr("lalk_server.app._fetch_models", fetch_models)
    app = create_app(
        config_path=tmp_path / "config.json",
        controller=cast(RuntimeController, StubController()),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/models",
            json={
                "base_url": "https://provider.example/v1",
                "api_key": "temporary-key",
            },
        )

    assert response.json() == {"models": ["model-a", "model-b"]}
    assert requests == [("https://provider.example/v1", "temporary-key")]


def test_websocket_rejects_unknown_browser_origin(tmp_path: Path) -> None:
    controller = StubController()
    app = create_app(
        config_path=tmp_path / "config.json",
        controller=cast(RuntimeController, controller),
    )

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as disconnect:
            with client.websocket_connect(
                "/ws",
                headers={"origin": "https://untrusted.example"},
            ) as websocket:
                websocket.receive_json()

    assert disconnect.value.code == 1008
