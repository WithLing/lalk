from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sdk" / "check_release_version.py"


def _load_release_checker():
    spec = importlib.util.spec_from_file_location("check_sdk_release_version", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_pyproject(root: Path, version: str) -> None:
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "lalk"\nversion = "{version}"\n',
        encoding="utf-8",
    )


def test_sdk_release_tag_matches_project_version(tmp_path: Path) -> None:
    checker = _load_release_checker()
    _write_pyproject(tmp_path, "1.2.3")

    assert checker.main("sdk-v1.2.3", tmp_path) == 0


def test_sdk_release_tag_rejects_version_mismatch(tmp_path: Path) -> None:
    checker = _load_release_checker()
    _write_pyproject(tmp_path, "1.2.4")

    assert checker.main("sdk-v1.2.3", tmp_path) == 1


def test_sdk_release_tag_rejects_invalid_format(tmp_path: Path) -> None:
    checker = _load_release_checker()
    _write_pyproject(tmp_path, "1.2.3")

    assert checker.main("v1.2.3", tmp_path) == 1
