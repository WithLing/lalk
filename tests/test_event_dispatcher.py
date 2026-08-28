import asyncio

import pytest

import lalk.observability._dispatcher as dispatcher_module
from lalk.observability import SessionEvent, SessionState, VoiceEvent
from lalk.observability._dispatcher import _EventDispatcher

pytestmark = pytest.mark.asyncio


async def test_dispatches_events_in_order_without_waiting_for_handler() -> None:
    release = asyncio.Event()
    received: list[SessionState] = []

    class Observer:
        async def on_event(self, event: VoiceEvent) -> None:
            assert isinstance(event, SessionEvent)
            received.append(event.state)
            if event.state is SessionState.STARTING:
                await release.wait()

    dispatcher = _EventDispatcher([Observer()])
    dispatcher.start()
    dispatcher.emit(SessionEvent(session_id="session", state=SessionState.STARTING))
    dispatcher.emit(SessionEvent(session_id="session", state=SessionState.READY))

    await asyncio.sleep(0)
    assert received == [SessionState.STARTING]

    release.set()
    await dispatcher.close()
    assert received == [SessionState.STARTING, SessionState.READY]


async def test_slow_observer_does_not_block_other_observers() -> None:
    release = asyncio.Event()
    received = asyncio.Event()

    class SlowObserver:
        async def on_event(self, event: VoiceEvent) -> None:
            await release.wait()

    class FastObserver:
        def on_event(self, event: VoiceEvent) -> None:
            received.set()

    dispatcher = _EventDispatcher([SlowObserver(), FastObserver()])
    dispatcher.start()
    dispatcher.emit(SessionEvent(session_id="session", state=SessionState.READY))

    async with asyncio.timeout(1):
        await received.wait()

    release.set()
    await dispatcher.close()


async def test_close_cancels_an_observer_that_does_not_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dispatcher_module, "_OBSERVER_CLOSE_TIMEOUT_SECONDS", 0.01)
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class Observer:
        async def on_event(self, event: VoiceEvent) -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    dispatcher = _EventDispatcher([Observer()])
    dispatcher.start()
    dispatcher.emit(SessionEvent(session_id="session", state=SessionState.READY))
    await started.wait()

    await dispatcher.close()

    assert cancelled.is_set()
