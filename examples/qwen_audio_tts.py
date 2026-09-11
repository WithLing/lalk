"""Stream text to Qwen Audio TTS and save the synthesized speech as WAV."""

import asyncio
import os
import wave

from _example_config import required_env

from lalk.audio import AudioChunk
from lalk.tts import QwenAudioTTS


async def main() -> None:
    async def text_parts():
        for part in ("你好，", "欢迎使用语音助手。", "我们开始聊天吧。"):
            yield part

    async with QwenAudioTTS(
        api_key=required_env("DASHSCOPE_API_KEY"),
        workspace_id=os.getenv("DASHSCOPE_WORKSPACE_ID"),
        voice=os.getenv("DASHSCOPE_TTS_VOICE", "longanhuan_v3.6"),
    ) as tts:
        stream = tts.synthesize(text_parts())
        with wave.open("qwen_audio_tts.wav", "wb") as output:
            output.setnchannels(tts.output_format.channels)
            output.setsampwidth(2)
            output.setframerate(tts.output_format.sample_rate)
            try:
                async for item in stream:
                    if isinstance(item, AudioChunk):
                        output.writeframes(item.data)
                    else:
                        print(f"[{item.at_frame}] {item.text}", flush=True)
            finally:
                await stream.aclose()
        print(await stream.result())


if __name__ == "__main__":
    asyncio.run(main())
