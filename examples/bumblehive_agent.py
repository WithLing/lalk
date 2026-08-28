"""Stream one response with BumblehiveAgent."""

import asyncio
import os

import bumblehive
from _example_config import required_env
from bumblehive.observability import (
    MODEL_STREAM_CONTENT_DELTA,
    MODEL_STREAM_REFUSAL_DELTA,
)

from lalk.agent import BumblehiveAgent


async def main() -> None:
    config = bumblehive.RuntimeArguments(
        model=os.getenv("BUMBLEHIVE_MODEL", "deepseek-chat"),
        api_key=required_env("BUMBLEHIVE_API_KEY"),
        base_url=os.getenv("BUMBLEHIVE_BASE_URL", "https://api.deepseek.com"),
        agent_instructions="回答天气问题前必须调用 get_weather 工具。",
        tool_names=["get_weather"],
    )
    agent = BumblehiveAgent(config)

    @agent.tools.tool(name="get_weather", description="查询指定城市的天气。")
    def get_weather(city: str) -> str:
        return f"{city}天气（示例数据）：晴，最高气温 30℃。"

    async with agent:
        stream = agent.stream("北京今天天气怎么样？")
        print("Assistant: ", end="", flush=True)

        async for event in stream:
            if event.kind in (
                MODEL_STREAM_CONTENT_DELTA,
                MODEL_STREAM_REFUSAL_DELTA,
            ):
                print(event.payload["delta"], end="", flush=True)

        result = await stream.result()

    print(f"\nUsage: {result.usage}")


if __name__ == "__main__":
    asyncio.run(main())
