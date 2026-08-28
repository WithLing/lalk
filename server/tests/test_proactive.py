import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from lalk_server.proactive import ProactiveRequest, ProactiveService
from lalk_server.storage import load_json


def test_request_strips_text_fields_and_rejects_whitespace_only_values() -> None:
    request = ProactiveRequest(
        id=" request-id ",
        title=" 会议提醒 ",
        instruction=" 提醒用户开会。 ",
        available_at=datetime.now(UTC),
    )

    assert request.id == "request-id"
    assert request.title == "会议提醒"
    assert request.instruction == "提醒用户开会。"

    for field in ("id", "title", "instruction"):
        values = {
            "id": "request-id",
            "title": "会议提醒",
            "instruction": "提醒用户开会。",
            "available_at": datetime.now(UTC),
        }
        values[field] = "   "
        with pytest.raises(ValueError):
            ProactiveRequest.model_validate(values)


@pytest.mark.asyncio
async def test_due_request_is_offered_and_removed_from_active_storage(
    tmp_path: Path,
) -> None:
    path = tmp_path / "proactive.json"
    offered: list[ProactiveRequest | None] = []
    changed = asyncio.Event()

    def on_offer(request: ProactiveRequest | None) -> None:
        offered.append(request)
        changed.set()

    service = ProactiveService(path, on_offer)
    await service.start()
    request = await service.enqueue(
        title="开会",
        instruction="提醒用户现在参加产品会议。",
        available_at=datetime.now(UTC),
    )
    await asyncio.wait_for(changed.wait(), timeout=1)

    assert offered[-1] is not None
    assert offered[-1].id == request.id
    assert (await service.get_offered(request.id)).title == "开会"

    await service.remove(request.id)

    assert offered[-1] is None
    assert load_json(path) == {"requests": []}
    await service.close()


@pytest.mark.asyncio
async def test_only_one_due_request_is_offered_at_a_time(tmp_path: Path) -> None:
    offered: list[ProactiveRequest | None] = []
    changed = asyncio.Event()

    def on_offer(request: ProactiveRequest | None) -> None:
        offered.append(request)
        changed.set()

    service = ProactiveService(tmp_path / "proactive.json", on_offer)
    await service.start()
    first = await service.enqueue(
        title="first",
        instruction="first instruction",
        available_at=datetime.now(UTC) - timedelta(seconds=2),
    )
    second = await service.enqueue(
        title="second",
        instruction="second instruction",
        available_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    await asyncio.wait_for(changed.wait(), timeout=1)

    assert offered[-1] is not None
    assert offered[-1].id == first.id

    changed.clear()
    await service.remove(first.id)
    await asyncio.wait_for(changed.wait(), timeout=1)
    if offered[-1] is None:
        changed.clear()
        await asyncio.wait_for(changed.wait(), timeout=1)
    assert offered[-1] is not None
    assert offered[-1].id == second.id
    await service.close()


@pytest.mark.asyncio
async def test_snooze_returns_offer_to_one_deadline_waiter(tmp_path: Path) -> None:
    offered: list[ProactiveRequest | None] = []
    changed = asyncio.Event()

    def on_offer(request: ProactiveRequest | None) -> None:
        offered.append(request)
        changed.set()

    service = ProactiveService(tmp_path / "proactive.json", on_offer)
    await service.start()
    request = await service.enqueue(
        title="later",
        instruction="say it later",
        available_at=datetime.now(UTC),
    )
    await asyncio.wait_for(changed.wait(), timeout=1)
    changed.clear()

    await service.snooze(
        request.id,
        datetime.now(UTC) + timedelta(milliseconds=30),
    )
    assert offered[-1] is None

    changed.clear()
    await asyncio.wait_for(changed.wait(), timeout=1)
    assert offered[-1] is not None
    assert offered[-1].id == request.id
    await service.close()
