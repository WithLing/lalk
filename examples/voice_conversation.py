"""Run a continuous local voice conversation with user interruptions."""

import asyncio
import os

import bumblehive
from _example_config import required_env, sensevoice_model_dir

from lalk import VoiceSession
from lalk.agent import VOICE_AGENT_INSTRUCTIONS, BumblehiveAgent
from lalk.asr import SenseVoiceASR
from lalk.audio import LocalAudio
from lalk.tts import VolcengineTTS
from lalk.turn_detection import SmartTurnV3
from lalk.vad import AdaptiveInputLevelGate, SileroVAD


async def main() -> None:
    session = VoiceSession(
        audio=LocalAudio(),
        vad=SileroVAD(),
        turn_analyzer=SmartTurnV3(),
        asr=SenseVoiceASR(model_dir=sensevoice_model_dir()),
        agent=BumblehiveAgent(
            bumblehive.RuntimeArguments(
                model=os.getenv("BUMBLEHIVE_MODEL", "deepseek-chat"),
                api_key=required_env("BUMBLEHIVE_API_KEY"),
                base_url=os.getenv("BUMBLEHIVE_BASE_URL", "https://api.deepseek.com"),
                agent_instructions=VOICE_AGENT_INSTRUCTIONS,
            )
        ),
        tts=VolcengineTTS(
            api_key=required_env("VOLCENGINE_API_KEY"),
            voice=os.getenv("VOLCENGINE_SPEAKER", "zh_female_vv_uranus_bigtts"),
            resource_id=os.getenv("VOLCENGINE_RESOURCE_ID", "seed-tts-2.0"),
        ),
        input_level_gate=AdaptiveInputLevelGate(),
    )

    print("Starting voice session... Press Ctrl+C to stop.")
    await session.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
