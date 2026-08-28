from pathlib import Path

import pytest
from lalk_server.history import (
    ConversationHistory,
    load_history,
    save_history,
)


@pytest.mark.asyncio
async def test_history_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    history = ConversationHistory(
        conversation_id="conversation-1",
        messages=[{"role": "user", "content": "你好"}],
        turns=[{"session_id": "session-1", "turn_id": 1}],
    )

    assert load_history(path) is None

    await save_history(path, history)

    assert load_history(path) == history
    assert path.stat().st_mode & 0o777 == 0o600
