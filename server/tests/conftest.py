from typing import Any

import pytest
from lalk_server.config import AppConfig


@pytest.fixture
def config_data() -> dict[str, Any]:
    return {
        "audio": {},
        "vad": {},
        "asr": {
            "provider": "qwen_audio",
            "settings": {
                "api_key": "asr-secret",
                "workspace_id": "workspace-id",
            },
        },
        "bumblehive": {
            "provider": {
                "type": "openai_chat_completions",
                "model": "test-model",
                "api_key": "agent-secret",
                "base_url": "https://example.test/v1",
            },
            "generation": {"temperature": 0.3},
            "agent": {"instructions": "Be concise."},
        },
        "tts": {
            "provider": "volcengine",
            "settings": {
                "api_key": "tts-secret",
                "voice": "test-voice",
            },
        },
    }


@pytest.fixture
def app_config(config_data: dict[str, Any]) -> AppConfig:
    return AppConfig.model_validate(config_data)
