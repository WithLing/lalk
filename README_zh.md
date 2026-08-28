<div align="center">

<img src="./desktop/brands/lalk/icons/app-icon.png" alt="Lalk" width="160">

# Lalk

**让实时语音交互更自然。**

一个实时语音 Agent Python SDK、服务端与桌面工作台。

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/macOS-Apple%20Silicon-black)](https://www.apple.com/macos/)

<p><a href="./README.md">English</a> | 简体中文</p>

</div>

---

## 项目简介

Lalk 将实时语音交互需要的完整链路放在同一个项目中：麦克风采集、语音活动检测、
语义回合检测、语音识别、Agent 执行、语音合成、实时打断、可观测能力、本地服务端，
以及基于 Tauri 的桌面应用。

Python SDK 采用模块化设计，音频、ASR、VAD、Agent、TTS 和回合检测组件都可以独立
替换。桌面端会把 Python 服务打包为本地 Sidecar，运行时通信保持在 localhost。

## 核心能力

- 支持自然打断的全双工实时语音会话。
- 基于 macOS VoiceProcessingIO 的原生音频与回声消除。
- Silero VAD、自适应输入门控和 Smart Turn 语义回合检测。
- 本地 ASR 与可替换的云服务语音识别实现。
- 基于 Bumblehive 的 Agent Runtime、流式事件与工具执行。
- 支持逐词播放标记的流式语音合成。
- 对话空闲策略与主动跟进能力。

## 平台支持

Lalk 当前面向 **搭载 M 系列芯片、运行 macOS 14 或更高版本的 Apple Silicon Mac**。

### 环境要求

- Apple Silicon Mac
- macOS 14+
- Python 3.11+
- Node.js 22+
- pnpm 10.33.0
- Rust stable 工具链
- Xcode Command Line Tools

## 快速开始

创建并激活 Python 环境：

```bash
conda create -n lalk_env python=3.11 -y
```

使用一个命令安装全部项目依赖并检查环境：

```bash
pnpm run setup
```

`setup` 会准备开发和桌面打包所需的 Python 与 Node.js 依赖。

如果通过默认 PyPI 源下载较慢，可以仅为本次安装临时使用清华 PyPI 镜像：

```bash
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple pnpm run setup
```

## 本地开发

启动本地 Server，默认监听 `127.0.0.1:17841`：

```bash
pnpm dev:server
```

在另一个终端中启动 WebUI：

```bash
pnpm dev:web
```

以开发模式启动桌面应用：

```bash
pnpm dev:desktop
```

## 构建桌面应用

生成 Apple Silicon macOS 应用和 DMG 安装包：

```bash
pnpm build:desktop
```

安装包输出目录：

```text
desktop/src-tauri/target/aarch64-apple-darwin/release/bundle/dmg/
```

构建流程会自动完成：

1. 编译原生 VoiceProcessingIO 动态库。
2. 将 Python 服务打包为 `lalk-server` Sidecar。
3. 构建 React WebUI。
4. 本地打包并签名 Tauri 应用。
5. 生成 Apple Silicon DMG。
