"""Persistent agent and desktop conversation history."""

import asyncio
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .storage import load_json, save_json


class ConversationHistory(BaseModel):
    """State required to continue one local conversation."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: str = Field(min_length=1)
    messages: list[dict[str, Any]]
    turns: list[dict[str, Any]]


def load_history(path: Path) -> ConversationHistory | None:
    """Load persisted conversation history when present."""

    data = load_json(path)
    return ConversationHistory.model_validate(data) if data is not None else None


async def save_history(path: Path, history: ConversationHistory) -> None:
    """Atomically persist one conversation snapshot."""

    await save_json(path, history.model_dump(mode="json"))


async def delete_history(path: Path) -> None:
    """Delete persisted conversation history when present."""

    await asyncio.to_thread(path.unlink, missing_ok=True)
