<div align="center">

<img src="./desktop/brands/lalk/icons/app-icon.png" alt="Lalk" width="160">

# Lalk

**Real-time voice agents, built for natural conversation.**

A Python SDK, server, and desktop workspace for real-time voice agents.

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/macOS-Apple%20Silicon-black)](https://www.apple.com/macos/)

<p>English | <a href="./README_zh.md">简体中文</a></p>

</div>

---

## Overview

Lalk brings the complete real-time voice pipeline into one project: microphone
capture, voice activity detection, turn detection, speech recognition, Agent
execution, speech synthesis, interruption handling, observability, a local
server, and a Tauri desktop application.

The Python SDK is modular, so each audio, ASR, VAD, Agent, TTS, and turn-detection
component can be replaced independently. The desktop application packages the
Python server as a local sidecar and keeps runtime traffic on localhost.

## Core Capabilities

- Full-duplex voice sessions with natural user interruption.
- Native macOS VoiceProcessingIO audio with echo cancellation.
- Silero VAD, adaptive input gating, and Smart Turn semantic turn detection.
- Local ASR and interchangeable cloud speech recognition implementations.
- Bumblehive-powered Agent runtime with streaming events and tool execution.
- Streaming TTS with word-level playback marks.
- Conversation inactivity policies and proactive follow-up support.

## Platform Support

Lalk currently targets **Apple Silicon Macs (M-series) running macOS 14 or
later**.

### Requirements

- Apple Silicon Mac
- macOS 14+
- Python 3.11+
- Node.js 22+
- pnpm 10.33.0
- Rust stable toolchain
- Xcode Command Line Tools

## Quick Start

Create and activate a Python environment:

```bash
conda create -n lalk_env python=3.11 -y
```

Install all project dependencies and verify the environment:

```bash
pnpm run setup
```

The setup command prepares the Python and Node.js dependencies required for
development and desktop packaging.

If downloading from the default PyPI index is slow, use the Tsinghua PyPI
mirror for this setup command only:

```bash
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple pnpm run setup
```

## Development

Start the local server on `127.0.0.1:17841`:

```bash
pnpm dev:server
```

In another terminal, start the WebUI:

```bash
pnpm dev:web
```

Start the desktop application in development mode:

```bash
pnpm dev:desktop
```

## Build the Desktop App

Create the Apple Silicon macOS application and DMG installer:

```bash
pnpm build:desktop
```

The installer is written to:

```text
desktop/src-tauri/target/aarch64-apple-darwin/release/bundle/dmg/
```

The build pipeline automatically:

1. Compiles the native VoiceProcessingIO library.
2. Packages the Python server as the `lalk-server` sidecar.
3. Builds the React WebUI.
4. Bundles and signs the Tauri application locally.
5. Creates the Apple Silicon DMG.
