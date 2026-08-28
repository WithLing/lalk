from datetime import UTC, datetime

from lalk_server.proactive import ProactiveRequest, ProactiveState
from lalk_server.protocol import (
    COMMAND_ADAPTER,
    NewConversationCommand,
    RuntimeView,
)

from lalk.observability import (
    AgentRequestEvent,
    AgentTextEvent,
    InputLevelEvent,
    InputSource,
    MetricsEvent,
    PlaybackEvent,
    PlaybackState,
    SessionEvent,
    SessionState,
    ToolCallFinishedEvent,
    ToolCallStartedEvent,
    TranscriptEvent,
    TurnEvent,
    TurnMetrics,
    TurnState,
    UserInputEvent,
)


def test_runtime_view_projects_live_transcript_until_turn_input() -> None:
    view = RuntimeView("running")
    queue = view.subscribe()
    queue.get_nowait()

    view.on_event(
        TranscriptEvent(
            session_id="session",
            text="你好",
            is_final=False,
            language="zh",
        )
    )

    message = queue.get_nowait()
    assert message["type"] == "transcript.update"
    assert message["data"]["is_final"] is False
    assert view.snapshot()["live_transcript"] == {
        "text": "你好",
        "is_final": False,
        "language": "zh",
    }

    view.on_event(
        UserInputEvent(
            session_id="session",
            turn_id=1,
            source=InputSource.VOICE,
            text="你好",
        )
    )
    assert view.snapshot()["live_transcript"] is None


def test_runtime_view_projects_ordered_text_and_tool_parts() -> None:
    view = RuntimeView("idle")
    view.on_event(SessionEvent(session_id="session", state=SessionState.STARTING))
    view.on_event(SessionEvent(session_id="session", state=SessionState.READY))
    view.on_event(
        UserInputEvent(
            session_id="session",
            turn_id=1,
            source=InputSource.TEXT,
            text="天气如何",
        )
    )
    view.on_event(TurnEvent(session_id="session", turn_id=1, state=TurnState.STARTED))
    view.on_event(AgentTextEvent(session_id="session", turn_id=1, delta="我查一下。"))
    view.on_event(
        ToolCallStartedEvent(
            session_id="session",
            turn_id=1,
            call_id="call-1",
            name="weather",
            arguments={"city": "上海"},
        )
    )
    assert view.stage == "tool_running"
    view.on_event(
        ToolCallFinishedEvent(
            session_id="session",
            turn_id=1,
            call_id="call-1",
            name="weather",
            result="晴",
            succeeded=True,
            elapsed_ms=25.0,
            file_changes=(
                {
                    "path": "sale_agent.md",
                    "added": 1,
                    "deleted": 1,
                    "unified_diff": (
                        "--- sale_agent.md\n"
                        "+++ sale_agent.md\n"
                        "@@ -4 +4 @@\n"
                        "-先介绍价格\n"
                        "+先询问招聘人数"
                    ),
                },
            ),
        )
    )
    view.on_event(AgentTextEvent(session_id="session", turn_id=1, delta="今天晴。"))
    view.on_event(
        PlaybackEvent(
            session_id="session",
            turn_id=1,
            state=PlaybackState.FINISHED,
            spoken_text="我查一下。今天晴。",
        )
    )
    metrics = TurnMetrics(turn_ms=100.0, llm_usage={"total_tokens": 12})
    view.on_event(MetricsEvent(session_id="session", turn_id=1, metrics=metrics))
    view.on_event(TurnEvent(session_id="session", turn_id=1, state=TurnState.COMPLETED))

    turn = view.snapshot()["turns"][0]
    assert turn["session_id"] == "session"
    assert turn["assistant"]["parts"] == [
        {"type": "text", "text": "我查一下。"},
        {
            "type": "tool",
            "call_id": "call-1",
            "name": "weather",
            "arguments": {"city": "上海"},
            "state": "succeeded",
            "result": "晴",
            "elapsed_ms": 25.0,
            "file_changes": [
                {
                    "path": "sale_agent.md",
                    "added": 1,
                    "deleted": 1,
                    "unified_diff": (
                        "--- sale_agent.md\n"
                        "+++ sale_agent.md\n"
                        "@@ -4 +4 @@\n"
                        "-先介绍价格\n"
                        "+先询问招聘人数"
                    ),
                }
            ],
        },
        {"type": "text", "text": "今天晴。"},
    ]
    assert turn["assistant"]["playback_state"] == "finished"
    assert turn["assistant"]["spoken_text"] == "我查一下。今天晴。"
    assert turn["metrics"]["turn_ms"] == 100.0
    assert view.stage == "listening"


def test_subscriber_receives_snapshot_then_ordered_events() -> None:
    view = RuntimeView("idle")
    queue = view.subscribe()

    first = queue.get_nowait()
    view.on_event(SessionEvent(session_id="session", state=SessionState.STARTING))
    second = queue.get_nowait()

    assert first["type"] == "snapshot"
    assert first["data"]["session_id"] is None
    assert second["type"] == "session.state"
    assert second["seq"] == 1
    assert second["stage"] == "starting"


def test_runtime_view_projects_microphone_input_level() -> None:
    view = RuntimeView("running")
    queue = view.subscribe()
    queue.get_nowait()

    view.on_event(
        InputLevelEvent(
            session_id="session",
            level=0.25,
            level_db=-12.0,
            noise_floor_db=-32.0,
            threshold_db=-25.0,
            gate_mode="normal",
            gate_passed=True,
        )
    )

    message = queue.get_nowait()
    assert message["type"] == "audio.input_level"
    assert message["data"]["level"] == 0.25
    assert message["data"]["threshold_db"] == -25.0
    assert view.snapshot()["input_level"] == 0.25
    assert view.snapshot()["input_gate"] == {
        "level_db": -12.0,
        "noise_floor_db": -32.0,
        "threshold_db": -25.0,
        "mode": "normal",
        "passed": True,
    }


def test_agent_request_event_exposes_count_without_model_messages() -> None:
    view = RuntimeView("idle")
    queue = view.subscribe()
    queue.get_nowait()

    view.on_event(
        AgentRequestEvent(
            session_id="session",
            turn_id=1,
            messages=(
                {"role": "system", "content": "private instructions"},
                {"role": "user", "content": "hello"},
            ),
        )
    )

    message = queue.get_nowait()
    assert message["type"] == "agent.request"
    assert message["data"] == {
        "session_id": "session",
        "turn_id": 1,
        "message_count": 2,
    }


def test_restored_turns_survive_a_new_session() -> None:
    restored = {
        "session_id": "previous-session",
        "turn_id": 1,
        "source": "text",
        "user_text": "previous",
        "state": "completed",
        "assistant": {
            "parts": [{"type": "text", "text": "answer"}],
            "playback_state": "finished",
            "spoken_text": "answer",
        },
        "metrics": None,
        "error": None,
    }
    view = RuntimeView("idle", turns=[restored])

    view.on_event(
        SessionEvent(session_id="current-session", state=SessionState.STARTING)
    )
    view.on_event(
        UserInputEvent(
            session_id="current-session",
            turn_id=1,
            source=InputSource.TEXT,
            text="current",
        )
    )

    turns = view.snapshot()["turns"]
    assert [turn["session_id"] for turn in turns] == [
        "previous-session",
        "current-session",
    ]
    assert view.persisted_turns() == [restored]


def test_session_stop_discards_an_uncommitted_turn() -> None:
    view = RuntimeView("idle")
    view.on_event(SessionEvent(session_id="session", state=SessionState.STARTING))
    view.on_event(
        UserInputEvent(
            session_id="session",
            turn_id=1,
            source=InputSource.TEXT,
            text="unfinished",
        )
    )
    view.on_event(TurnEvent(session_id="session", turn_id=1, state=TurnState.STARTED))

    assert len(view.snapshot()["turns"]) == 1

    view.on_event(SessionEvent(session_id="session", state=SessionState.STOPPED))

    assert view.snapshot()["turns"] == []


def test_new_conversation_command_and_projection() -> None:
    command = COMMAND_ADAPTER.validate_python(
        {"id": "new-1", "type": "conversation.new"}
    )
    view = RuntimeView(
        "idle",
        turns=[
            {
                "session_id": "session",
                "turn_id": 1,
                "state": "completed",
            }
        ],
    )

    assert isinstance(command, NewConversationCommand)

    view.new_conversation()

    assert view.snapshot()["turns"] == []


def test_proactive_offer_and_hidden_input_are_projected_safely() -> None:
    view = RuntimeView("running")
    queue = view.subscribe()
    queue.get_nowait()
    request = ProactiveRequest(
        id="request-1",
        title="产品会议",
        instruction="private agent instruction",
        available_at=datetime.now(UTC),
        state=ProactiveState.OFFERED,
    )

    view.set_proactive_offer(request)
    offer_message = queue.get_nowait()
    view.on_event(
        UserInputEvent(
            session_id="session",
            turn_id=1,
            source=InputSource.PROACTIVE,
            text="private agent instruction",
        )
    )
    input_message = queue.get_nowait()

    assert offer_message["data"]["offer"] == {
        "id": "request-1",
        "title": "产品会议",
        "available_at": request.available_at.isoformat(),
        "state": "offered",
    }
    assert "instruction" not in offer_message["data"]["offer"]
    assert input_message["data"]["text"] == ""
    assert view.snapshot()["turns"][0]["source"] == "proactive"
    assert view.snapshot()["turns"][0]["user_text"] == ""


def test_followup_internal_input_is_hidden() -> None:
    view = RuntimeView("running")
    queue = view.subscribe()
    queue.get_nowait()

    view.on_event(
        UserInputEvent(
            session_id="session",
            turn_id=1,
            source=InputSource.FOLLOWUP,
            text="private follow-up instruction",
        )
    )
    message = queue.get_nowait()

    assert message["data"]["text"] == ""
    assert view.snapshot()["turns"][0]["source"] == "followup"
    assert view.snapshot()["turns"][0]["user_text"] == ""


def test_opening_internal_input_is_hidden() -> None:
    view = RuntimeView("running")
    queue = view.subscribe()
    queue.get_nowait()

    view.on_event(
        UserInputEvent(
            session_id="session",
            turn_id=1,
            source=InputSource.OPENING,
            text="private opening instruction",
        )
    )
    message = queue.get_nowait()

    assert message["data"]["text"] == ""
    assert view.snapshot()["turns"][0]["source"] == "opening"
    assert view.snapshot()["turns"][0]["user_text"] == ""
