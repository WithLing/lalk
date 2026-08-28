"""Resolve files that may live inside a PyInstaller sidecar bundle."""

from __future__ import annotations

import sys
from pathlib import Path


def resolve_resource_path(value: str | Path) -> Path:
    """Return a usable path in source checkouts and packaged sidecars."""

    path = Path(value).expanduser()
    if path.is_absolute():
        return path

    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root is not None:
        bundled = Path(bundle_root) / path
        if bundled.exists():
            return bundled

    project_root = Path(__file__).resolve().parents[3]
    source_path = project_root / path
    if source_path.exists():
        return source_path

    return path
