"""Build the macOS VoiceProcessingIO dynamic library for this machine."""

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "src" / "lalk" / "audio" / "_native" / "VoiceIO.swift"
OUTPUT = (
    PROJECT_ROOT
    / "src"
    / "lalk"
    / "audio"
    / "_native"
    / "libLalkVoiceIO.dylib"
)
BUILD_DIR = PROJECT_ROOT / "build" / "macos_voice_processing"
MACOS_DEPLOYMENT_TARGET = "14.0"
ARCHITECTURES = ("arm64", "x86_64")


def main() -> None:
    if sys.platform != "darwin":
        raise RuntimeError("VoiceProcessingIO can only be built on macOS")

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["CLANG_MODULE_CACHE_PATH"] = str(BUILD_DIR / "clang-cache")
    environment["SWIFT_MODULECACHE_PATH"] = str(BUILD_DIR / "swift-cache")

    libraries: list[Path] = []
    for architecture in ARCHITECTURES:
        library = BUILD_DIR / f"VoiceIO-{architecture}.dylib"
        command = [
            "xcrun",
            "swiftc",
            "-target",
            f"{architecture}-apple-macosx{MACOS_DEPLOYMENT_TARGET}",
            "-O",
            "-parse-as-library",
            "-emit-library",
            str(SOURCE),
            "-o",
            str(library),
            "-Xlinker",
            "-install_name",
            "-Xlinker",
            "@rpath/libLalkVoiceIO.dylib",
            "-framework",
            "AVFoundation",
            "-framework",
            "CoreAudio",
            "-framework",
            "Foundation",
        ]
        subprocess.run(command, check=True, env=environment)
        libraries.append(library)

    subprocess.run(
        ["lipo", "-create", *map(str, libraries), "-output", str(OUTPUT)],
        check=True,
    )
    subprocess.run(
        ["lipo", str(OUTPUT), "-verify_arch", *ARCHITECTURES],
        check=True,
    )
    subprocess.run(["codesign", "--force", "--sign", "-", str(OUTPUT)], check=True)
    print(f"VoiceProcessingIO ready: {OUTPUT}")


if __name__ == "__main__":
    main()
