"""Lalk local server."""

__all__ = ["create_app"]


def __getattr__(name: str):
    # Keep CLI help independent of audio and model imports.
    if name == "create_app":
        from .app import create_app

        return create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
