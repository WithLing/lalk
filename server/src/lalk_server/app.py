"""FastAPI application for the Lalk desktop sidecar."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from openai import AsyncOpenAI, OpenAIError
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError

from .config import AppConfig
from .protocol import (
    COMMAND_ADAPTER,
    AnswerProactiveCommand,
    DismissProactiveCommand,
    InterruptCommand,
    NewConversationCommand,
    RuntimeView,
    SnoozeProactiveCommand,
    StartCommand,
    StopCommand,
    SubmitTextCommand,
)
from .runtime import CommandError, RuntimeController

logger = logging.getLogger(__name__)

DEFAULT_ORIGINS = (
    "http://127.0.0.1:17840",
    "http://localhost:17840",
    "http://tauri.localhost",
    "tauri://localhost",
)


class ModelListRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    base_url: HttpUrl
    api_key: str = Field(min_length=1)


def create_app(
    *,
    config_path: Path | None = None,
    controller: RuntimeController | None = None,
) -> FastAPI:
    """Create one local single-session server application."""

    resolved_config_path = _resolve_config_path(config_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime = controller or RuntimeController(resolved_config_path)
        app.state.runtime = runtime
        await runtime.start_background()
        try:
            yield
        finally:
            await runtime.close()

    app = FastAPI(title="Lalk Server", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(DEFAULT_ORIGINS),
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type"],
    )

    @app.get("/health")
    async def health(request: Request) -> dict[str, str]:
        runtime = _runtime(request)
        return {"status": "ok", "runtime_state": runtime.view.runtime_state}

    @app.get("/api/config")
    async def get_config(request: Request) -> dict[str, object]:
        return _runtime(request).config_response()

    @app.put("/api/config")
    async def put_config(
        config: AppConfig,
        request: Request,
    ) -> dict[str, object]:
        try:
            return await _runtime(request).update_config(config)
        except CommandError as error:
            raise HTTPException(status_code=409, detail=error.code) from error

    @app.post("/api/models")
    async def list_models(request: ModelListRequest) -> dict[str, list[str]]:
        try:
            models = await _fetch_models(str(request.base_url), request.api_key)
        except OpenAIError as error:
            raise HTTPException(
                status_code=502,
                detail="无法从模型服务获取模型列表",
            ) from error
        return {"models": models}

    @app.websocket("/ws")
    async def runtime_socket(websocket: WebSocket) -> None:
        origin = websocket.headers.get("origin")
        if origin is not None and origin not in DEFAULT_ORIGINS:
            await websocket.close(code=1008, reason="Origin not allowed")
            return
        await websocket.accept()
        runtime = websocket.app.state.runtime
        view = runtime.view
        try:
            queue = view.subscribe()
        except RuntimeError:
            await websocket.close(
                code=1008,
                reason="Runtime WebSocket already connected",
            )
            return

        sender = asyncio.create_task(
            _send_messages(websocket, queue),
            name="lalk-websocket-sender",
        )
        try:
            while True:
                raw = await websocket.receive_json()
                try:
                    command = COMMAND_ADAPTER.validate_python(raw)
                except ValidationError as error:
                    command_id = raw.get("id") if isinstance(raw, dict) else None
                    if isinstance(command_id, str) and command_id:
                        view.send_command_result(
                            command_id,
                            ok=False,
                            error={"code": "invalid_command", "message": str(error)},
                        )
                        continue
                    await websocket.close(code=1008, reason="Invalid command")
                    return
                await _execute_command(runtime, view, command)
        except WebSocketDisconnect:
            pass
        finally:
            view.unsubscribe(queue)
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)

    return app


async def _execute_command(
    runtime: RuntimeController,
    view: RuntimeView,
    command: (
        StartCommand
        | StopCommand
        | InterruptCommand
        | SubmitTextCommand
        | NewConversationCommand
        | AnswerProactiveCommand
        | DismissProactiveCommand
        | SnoozeProactiveCommand
    ),
) -> None:
    try:
        match command:
            case StartCommand():
                data = {"session_id": await runtime.start()}
            case StopCommand():
                data = {"stopped": await runtime.stop()}
            case InterruptCommand():
                data = {"interrupted": runtime.interrupt()}
            case SubmitTextCommand(text=text):
                runtime.submit_text(text)
                data = {"accepted": True}
            case NewConversationCommand():
                data = {"conversation_id": await runtime.new_conversation()}
            case AnswerProactiveCommand(request_id=request_id):
                data = {"session_id": await runtime.answer_proactive(request_id)}
            case DismissProactiveCommand(request_id=request_id):
                await runtime.dismiss_proactive(request_id)
                data = {"dismissed": True}
            case SnoozeProactiveCommand(
                request_id=request_id,
                minutes=minutes,
            ):
                await runtime.snooze_proactive(request_id, minutes)
                data = {"snoozed": True}
        view.send_command_result(command.id, ok=True, data=data)
    except CommandError as error:
        view.send_command_result(
            command.id,
            ok=False,
            error={"code": error.code, "message": str(error)},
        )
    except Exception as error:
        logger.exception("Runtime command failed")
        view.send_command_result(
            command.id,
            ok=False,
            error={"code": "runtime_error", "message": str(error)},
        )


async def _send_messages(
    websocket: WebSocket,
    queue: asyncio.Queue[dict[str, object]],
) -> None:
    while True:
        message = await queue.get()
        await websocket.send_json(message)
        if message["type"] == "stream.overflow":
            await websocket.close(code=1013, reason="Runtime event stream overflow")
            return


def _runtime(request: Request) -> RuntimeController:
    return request.app.state.runtime


def _resolve_config_path(config_path: Path | None) -> Path:
    return (config_path or Path.home() / ".lalk" / "config.json").expanduser()


async def _fetch_models(base_url: str, api_key: str) -> list[str]:
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    try:
        response = await client.models.list()
        return list(dict.fromkeys(model.id for model in response.data if model.id))
    finally:
        await client.close()
