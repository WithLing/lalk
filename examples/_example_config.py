"""Shared configuration helpers for the runnable examples."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def required_env(name: str) -> str:
    """Return one required environment variable with a useful error."""

    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Set {name} before running this example.")
    return value


def sensevoice_model_dir() -> Path:
    """Resolve and validate the SenseVoice model directory."""

    configured = os.getenv("LALK_SENSEVOICE_MODEL_DIR", "").strip()
    model_dir = (
        Path(configured).expanduser()
        if configured
        else PROJECT_ROOT / "models" / "sensevoice"
    )
    required_files = ("model.int8.onnx", "tokens.txt")
    missing = [name for name in required_files if not (model_dir / name).is_file()]
    if missing:
        names = ", ".join(missing)
        raise SystemExit(
            f"SenseVoice model files are missing from {model_dir}: {names}. "
            "Set LALK_SENSEVOICE_MODEL_DIR to a directory containing both files."
        )
    return model_dir
