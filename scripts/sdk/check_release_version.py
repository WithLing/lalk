"""Validate that an SDK release tag matches the package version."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TAG_PATTERN = re.compile(r"sdk-v(?P<version>\d+\.\d+\.\d+)")


def main(tag: str, root: Path = ROOT) -> int:
    match = TAG_PATTERN.fullmatch(tag)
    if match is None:
        print("SDK release tags must use the form sdk-vX.Y.Z.", file=sys.stderr)
        return 1

    expected = match.group("version")
    with (root / "pyproject.toml").open("rb") as file:
        actual = str(tomllib.load(file)["project"]["version"])

    if actual != expected:
        print(
            f"Release tag {tag} expects SDK version {expected}, "
            f"but pyproject.toml contains {actual}.",
            file=sys.stderr,
        )
        return 1

    print(f"SDK release version verified: {expected}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: python scripts/sdk/check_release_version.py sdk-vX.Y.Z"
        )
    raise SystemExit(main(sys.argv[1]))
