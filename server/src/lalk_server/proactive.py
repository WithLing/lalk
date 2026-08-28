"""Persist and offer desktop-initiated agent requests."""

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from lalk.agent import BumblehiveAgent

from .storage import load_json, save_json


class ProactiveState(StrEnum):
    """Active lifecycle states kept on disk."""

    PENDING = "pending"
    OFFERED = "offered"


class ProactiveRequest(BaseModel):
    """One request that may initiate a future voice turn."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=160)
    instruction: str = Field(min_length=1, max_length=4_000)
    available_at: datetime
    state: ProactiveState = ProactiveState.PENDING

    @field_validator("available_at")
    @classmethod
    def normalize_available_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("available_at must include a timezone")
        return value.astimezone(UTC)


class _ProactiveDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requests: list[ProactiveRequest] = Field(default_factory=list)


class ProactiveNotFoundError(KeyError):
    """The requested proactive item does not exist."""


class ProactiveStateError(RuntimeError):
    """The requested operation is invalid for the current item state."""


OfferCallback = Callable[[ProactiveRequest | None], None]


class ProactiveService:
    """Keep active requests and wake exactly when the next one becomes due."""

    def __init__(self, path: Path, on_offer: OfferCallback) -> None:
        self._path = path
        self._on_offer = on_offer
        self._requests: dict[str, ProactiveRequest] = {}
        self._lock = asyncio.Lock()
        self._changed = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Restore active requests and start the single deadline waiter."""

        async with self._lock:
            if self._task is not None:
                return
            raw = await asyncio.to_thread(load_json, self._path)
            document = _ProactiveDocument.model_validate(raw or {})
            requests = [
                request.model_copy(update={"state": ProactiveState.PENDING})
                for request in document.requests
            ]
            self._requests = {request.id: request for request in requests}
            if any(
                request.state is ProactiveState.OFFERED for request in document.requests
            ):
                await self._save_locked()
            self._task = asyncio.create_task(
                self._run(),
                name="lalk-proactive-waiter",
            )
            self._changed.set()

    async def close(self) -> None:
        """Stop the deadline waiter without removing stored requests."""

        async with self._lock:
            task = self._task
            self._task = None
            self._changed.set()
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def enqueue(
        self,
        *,
        title: str,
        instruction: str,
        available_at: datetime,
    ) -> ProactiveRequest:
        """Store one future or immediately available request."""

        request = ProactiveRequest(
            id=uuid.uuid4().hex,
            title=title,
            instruction=instruction,
            available_at=available_at,
        )
        async with self._lock:
            self._requests[request.id] = request
            await self._save_locked()
            self._changed.set()
        return request

    async def get_offered(self, request_id: str) -> ProactiveRequest:
        """Return an offered request, rejecting stale desktop actions."""

        async with self._lock:
            request = self._require_locked(request_id)
            if request.state is not ProactiveState.OFFERED:
                raise ProactiveStateError("The proactive request is not offered")
            return request

    async def remove(self, request_id: str) -> None:
        """Remove a completed, dismissed, or cancelled active request."""

        async with self._lock:
            request = self._require_locked(request_id)
            del self._requests[request_id]
            await self._save_locked()
            if request.state is ProactiveState.OFFERED:
                self._on_offer(None)
            self._changed.set()

    async def snooze(self, request_id: str, available_at: datetime) -> None:
        """Return an offered request to pending with a new deadline."""

        normalized = ProactiveRequest.normalize_available_at(available_at)
        async with self._lock:
            request = self._require_locked(request_id)
            if request.state is not ProactiveState.OFFERED:
                raise ProactiveStateError("The proactive request is not offered")
            self._requests[request_id] = request.model_copy(
                update={
                    "available_at": normalized,
                    "state": ProactiveState.PENDING,
                }
            )
            await self._save_locked()
            self._on_offer(None)
            self._changed.set()

    async def _run(self) -> None:
        while True:
            timeout: float | None = None
            async with self._lock:
                self._changed.clear()
                if not self._offered_locked():
                    pending = [
                        request
                        for request in self._requests.values()
                        if request.state is ProactiveState.PENDING
                    ]
                    if pending:
                        next_request = min(
                            pending,
                            key=lambda request: request.available_at,
                        )
                        now = datetime.now(UTC)
                        if next_request.available_at <= now:
                            offered = next_request.model_copy(
                                update={"state": ProactiveState.OFFERED}
                            )
                            self._requests[offered.id] = offered
                            await self._save_locked()
                            self._on_offer(offered)
                        else:
                            timeout = (next_request.available_at - now).total_seconds()

            if timeout is None:
                await self._changed.wait()
                continue
            try:
                await asyncio.wait_for(self._changed.wait(), timeout=timeout)
            except TimeoutError:
                pass

    def _offered_locked(self) -> ProactiveRequest | None:
        return next(
            (
                request
                for request in self._requests.values()
                if request.state is ProactiveState.OFFERED
            ),
            None,
        )

    def _require_locked(self, request_id: str) -> ProactiveRequest:
        try:
            return self._requests[request_id]
        except KeyError as error:
            raise ProactiveNotFoundError(request_id) from error

    async def _save_locked(self) -> None:
        document = _ProactiveDocument(requests=list(self._requests.values()))
        await save_json(self._path, document.model_dump(mode="json"))


def register_proactive_tools(
    agent: BumblehiveAgent,
    service: ProactiveService,
) -> None:
    """Register the minimal agent-facing API on a Bumblehive agent."""

    tools = agent.tools

    @tools.tool(
        name="schedule_proactive",
        description=(
            "当用户要求未来提醒或主动联系时，必须调用此工具，不能只口头答应。"
            "available_at 是包含时区的 ISO 8601 时间；instruction 描述届时"
            "主动对话的目标，而不是现在回复用户的话。"
        ),
    )
    async def schedule_proactive(
        title: str,
        instruction: str,
        available_at: str,
    ) -> dict[str, str]:
        try:
            deadline = datetime.fromisoformat(available_at.replace("Z", "+00:00"))
            request = await service.enqueue(
                title=title,
                instruction=instruction,
                available_at=deadline,
            )
        except ValueError as error:
            raise ValueError(f"Invalid proactive request: {error}") from error
        return {
            "id": request.id,
            "title": request.title,
            "available_at": request.available_at.isoformat(),
        }

    @tools.tool(
        name="cancel_proactive",
        description="取消一个尚未处理的主动联系请求。",
    )
    async def cancel_proactive(request_id: str) -> dict[str, bool]:
        try:
            await service.remove(request_id)
        except ProactiveNotFoundError as error:
            raise ValueError("Proactive request not found") from error
        return {"cancelled": True}
