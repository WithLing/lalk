from unittest.mock import Mock

import lalk_server.runtime as runtime
import pytest
from lalk_server.config import AppConfig, load_config, save_config
from lalk_server.runtime import build_tts


@pytest.mark.asyncio
@pytest.mark.parametrize("workspace", ["", "workspace"])
async def test_qwen_tts_roundtrip_and_factory(
    config_data, tmp_path, monkeypatch, workspace
):
    config_data["tts"] = {
        "provider": "qwen_audio",
        "settings": {
            "api_key": "test-key",
            "workspace_id": workspace,
            "voice": "cloned-voice",
            "voice_kind": "clone",
        },
    }
    config = AppConfig.model_validate(config_data)
    path = tmp_path / "config.json"
    await save_config(path, config)
    assert load_config(path) == config
    constructor = Mock()
    monkeypatch.setattr(runtime, "QwenAudioTTS", constructor)
    assert build_tts(config) is constructor.return_value
    constructor.assert_called_once_with(
        api_key="test-key",
        workspace_id=workspace or None,
        voice="cloned-voice",
        sample_rate=48000,
    )


def test_volcengine_factory_remains_provider_specific(app_config, monkeypatch):
    constructor = Mock()
    monkeypatch.setattr(runtime, "VolcengineTTS", constructor)
    build_tts(app_config)
    assert constructor.call_args.kwargs["resource_id"] == "seed-tts-2.0"
    assert "workspace_id" not in constructor.call_args.kwargs
