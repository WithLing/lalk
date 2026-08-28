"""Run the Lalk local sidecar."""

import argparse
from pathlib import Path

import uvicorn

from .app import create_app


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Lalk local server")
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to the server JSON configuration",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=17841,
        help="Localhost port (default: 17841)",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    uvicorn.run(
        create_app(config_path=args.config),
        host="127.0.0.1",
        port=args.port,
        workers=1,
    )


if __name__ == "__main__":
    main()
