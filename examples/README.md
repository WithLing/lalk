# Lalk Examples

Run examples from the repository root after creating the environment and running
`pnpm run setup`.

## Configuration

The local audio examples need microphone permission. Local SenseVoice examples
also need `model.int8.onnx` and `tokens.txt`. Put them in
`models/sensevoice/`, or set `LALK_SENSEVOICE_MODEL_DIR` to their directory.

Cloud examples read credentials from environment variables:

| Variable | Used by | Required |
| --- | --- | --- |
| `BUMBLEHIVE_API_KEY` | Bumblehive Agent | Yes |
| `BUMBLEHIVE_MODEL` | Bumblehive Agent model | No; defaults to `deepseek-chat` |
| `BUMBLEHIVE_BASE_URL` | Bumblehive Agent endpoint | No; defaults to DeepSeek |
| `VOLCENGINE_API_KEY` | Volcengine TTS | Yes |
| `VOLCENGINE_SPEAKER` | Volcengine voice | No |
| `VOLCENGINE_RESOURCE_ID` | Volcengine resource | No |
| `DASHSCOPE_API_KEY` | Qwen Audio ASR | Yes |
| `DASHSCOPE_WORKSPACE_ID` | Qwen workspace | No |

## Suggested Order

1. `python examples/local_audio_record_playback.py` — record and replay three seconds.
2. `python examples/local_audio_vad.py` — print microphone speech-state changes.
3. `python examples/local_audio_asr.py` — record once and transcribe locally.
4. `python examples/local_audio_vad_asr.py` — continuously transcribe local speech.
5. `python examples/bumblehive_agent.py` — stream an Agent response with a tool call.
6. `python examples/volcengine_tts.py` — synthesize and play one sentence.
7. `python examples/agent_tts_playback.py` — stream Agent text into speech playback.
8. `python examples/qwen_audio_asr.py` — continuously transcribe with Qwen Audio.
9. `python examples/voice_conversation.py` — run the complete interruptible voice loop.

Continuous examples stop cleanly with `Ctrl+C`.
