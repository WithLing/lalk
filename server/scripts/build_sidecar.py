"""Build the Lalk server as a PyInstaller onedir Tauri resource."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = PROJECT_ROOT / "server"
TAURI_ROOT = PROJECT_ROOT / "desktop" / "src-tauri"
VOICE_IO_LIBRARY = (
    PROJECT_ROOT
    / "src/lalk/audio/_native"
    / "libLalkVoiceIO.dylib"
)


def _copy_metadata_args(*distributions: str) -> list[str]:
    arguments: list[str] = []
    for distribution in distributions:
        try:
            importlib.metadata.distribution(distribution)
        except importlib.metadata.PackageNotFoundError:
            continue
        arguments.extend(("--copy-metadata", distribution))
    return arguments


def _deduplicate_sherpa_onnx_runtime(output: Path, binary_name: str) -> None:
    """Keep the sherpa ONNX Runtime only at the rpath used by its binaries."""

    internal = output / binary_name / "_internal"
    root_runtimes = tuple(internal.glob("libonnxruntime.*.dylib"))
    if len(root_runtimes) != 1:
        raise RuntimeError(
            "Expected one versioned sherpa ONNX Runtime link at "
            f"{internal}, found {len(root_runtimes)}"
        )

    root_runtime = root_runtimes[0]
    if not root_runtime.is_symlink():
        raise RuntimeError(f"Expected a symlink at {root_runtime}")
    bundled_runtime = root_runtime.resolve(strict=True)
    sherpa_library_dir = internal / "sherpa_onnx" / "lib"
    if bundled_runtime.parent != sherpa_library_dir:
        raise RuntimeError(
            f"Unexpected sherpa ONNX Runtime target: {bundled_runtime}"
        )

    root_runtime.unlink()
    shutil.move(bundled_runtime, root_runtime)

    unversioned_runtime = sherpa_library_dir / "libonnxruntime.dylib"
    if not unversioned_runtime.is_file():
        raise RuntimeError(
            f"Expected the unversioned sherpa ONNX Runtime at {unversioned_runtime}"
        )
    unversioned_runtime.unlink()


def main() -> None:
    if sys.platform != "darwin":
        raise SystemExit("Desktop packaging currently supports macOS only")
    if importlib.util.find_spec("PyInstaller") is None:
        raise SystemExit(
            "PyInstaller is missing; install the project build dependencies "
            "in the active Python environment"
        )

    subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts/build_macos_voice_processing.py")],
        check=True,
    )

    machine = platform.machine().lower()
    target = "aarch64-apple-darwin" if machine == "arm64" else "x86_64-apple-darwin"
    binary_name = "lalk-server"
    output_dir = TAURI_ROOT / "sidecar"
    build_dir = PROJECT_ROOT / "build" / "sidecar" / target
    output_dir.mkdir(parents=True, exist_ok=True)
    build_dir.mkdir(parents=True, exist_ok=True)

    environment = os.environ.copy()
    environment["PYINSTALLER_CONFIG_DIR"] = str(build_dir / "cache")
    data_separator = os.pathsep
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        binary_name,
        "--distpath",
        str(output_dir),
        "--workpath",
        str(build_dir / "work"),
        "--specpath",
        str(build_dir),
        "--paths",
        str(PROJECT_ROOT / "src"),
        "--paths",
        str(SERVER_ROOT / "src"),
        "--collect-all",
        "sherpa_onnx",
        "--collect-binaries",
        "numpy",
        "--collect-submodules",
        "bumblehive",
        "--collect-data",
        "bumblehive",
        "--collect-submodules",
        "uvicorn",
        "--collect-submodules",
        "websockets",
        "--add-data",
        (
            f"{PROJECT_ROOT / 'src/lalk/vad/data'}"
            f"{data_separator}lalk/vad/data"
        ),
        "--add-data",
        (
            f"{PROJECT_ROOT / 'src/lalk/turn_detection/data'}"
            f"{data_separator}lalk/turn_detection/data"
        ),
        "--add-data",
        (
            f"{VOICE_IO_LIBRARY}"
            f"{data_separator}lalk/audio/_native"
        ),
        "--hidden-import",
        "bumblehive.agent.context.prompts",
        *_copy_metadata_args("bumblehive", "fastmcp", "fastmcp-slim"),
        str(SERVER_ROOT / "sidecar.py"),
    ]
    subprocess.run(command, cwd=PROJECT_ROOT, env=environment, check=True)
    _deduplicate_sherpa_onnx_runtime(output_dir, binary_name)

    executable = output_dir / binary_name / binary_name
    if not executable.is_file():
        raise RuntimeError(f"Sidecar output missing: {executable}")
    print(f"Sidecar ready: {executable}")


if __name__ == "__main__":
    main()
