"""Shared JSON file persistence."""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any | None:
    """Load one JSON document, or return None when it does not exist."""

    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


async def save_json(path: Path, data: Any) -> None:
    """Atomically replace one JSON document."""

    await asyncio.to_thread(_save_json, path, data)


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
