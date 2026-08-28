import json
from pathlib import Path

import pytest
from lalk_server.config import (
    AppConfig,
    load_config,
    save_config,
)


@pytest.mark.asyncio
async def test_config_round_trip_preserves_api_keys(
    tmp_path: Path,
    app_config: AppConfig,
) -> None:
    path = tmp_path / "nested" / "config.json"

    await save_config(path, app_config)

    assert load_config(path) == app_config
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["asr"]["settings"]["api_key"] == "asr-secret"
    assert saved["tts"]["settings"]["api_key"] == "tts-secret"
    assert saved["bumblehive"]["provider"]["api_key"] == "agent-secret"
    assert path.stat().st_mode & 0o777 == 0o600


def test_invalid_config_is_not_silently_replaced(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"tts": {}}), encoding="utf-8")

    with pytest.raises(ValueError):
        load_config(path)


def test_vad_input_level_gate_has_one_bounded_setting(
    config_data: dict[str, object],
) -> None:
    config = AppConfig.model_validate(config_data)
    assert config.vad.min_input_level == 0.0
    assert config.vad.adaptive_input_level is True

    vad = config_data["vad"]
    assert isinstance(vad, dict)
    vad["min_input_level"] = 0.2
    assert AppConfig.model_validate(config_data).vad.min_input_level == 0.2

    vad["min_input_level"] = 1.1
    with pytest.raises(ValueError):
        AppConfig.model_validate(config_data)


def test_semantic_turn_detection_has_pipecat_timing_defaults(
    config_data: dict[str, object],
) -> None:
    config = AppConfig.model_validate(config_data)

    assert config.vad.speech_end_ms == 300
    assert config.turn_detection.incomplete_timeout_ms == 3000

    config_data["turn_detection"] = {"incomplete_timeout_ms": 0}
    with pytest.raises(ValueError):
        AppConfig.model_validate(config_data)


def test_interruption_filter_is_configurable(
    config_data: dict[str, object],
) -> None:
    config = AppConfig.model_validate(config_data)
    assert config.interruption.backchannel_filter_enabled is True
    assert config.interruption.backchannel_phrases is None

    config_data["interruption"] = {
        "backchannel_filter_enabled": False,
        "backchannel_phrases": ["嗯哼", "うんうん"],
    }
    interruption = AppConfig.model_validate(config_data).interruption

    assert interruption.backchannel_filter_enabled is False
    assert interruption.backchannel_phrases == ["嗯哼", "うんうん"]


def test_flat_provider_settings_are_rejected(config_data: dict[str, object]) -> None:
    asr = config_data["asr"]
    assert isinstance(asr, dict)
    settings = asr.pop("settings")
    assert isinstance(settings, dict)
    asr.update(settings)

    with pytest.raises(ValueError):
        AppConfig.model_validate(config_data)


def test_asr_workspace_id_is_optional(config_data: dict[str, object]) -> None:
    asr = config_data["asr"]
    assert isinstance(asr, dict)
    settings = asr["settings"]
    assert isinstance(settings, dict)
    settings.pop("workspace_id")

    config = AppConfig.model_validate(config_data)

    assert config.asr.settings.workspace_id == ""


def test_bumblehive_api_key_is_required(config_data: dict[str, object]) -> None:
    bumblehive = config_data["bumblehive"]
    assert isinstance(bumblehive, dict)
    provider = bumblehive["provider"]
    assert isinstance(provider, dict)
    provider.pop("api_key")

    with pytest.raises(ValueError, match="bumblehive.provider.api_key is required"):
        AppConfig.model_validate(config_data)


def test_opening_is_disabled_by_default_and_requires_a_boolean(
    config_data: dict[str, object],
) -> None:
    assert AppConfig.model_validate(config_data).opening_enabled is False

    config_data["opening_enabled"] = True
    assert AppConfig.model_validate(config_data).opening_enabled is True

    config_data["opening_enabled"] = 1
    with pytest.raises(ValueError):
        AppConfig.model_validate(config_data)


def test_legacy_agent_content_enables_personalization(
    config_data: dict[str, object],
) -> None:
    config = AppConfig.model_validate(config_data)

    assert config.personalization_enabled is True
    assert config.bumblehive["agent"] == {"instructions": "Be concise."}


def test_disabled_personalization_removes_agent_content(
    config_data: dict[str, object],
) -> None:
    config_data["personalization_enabled"] = False
    bumblehive = config_data["bumblehive"]
    assert isinstance(bumblehive, dict)
    bumblehive["agent"] = {
        "instructions": "Do not save this.",
        "dynamic_context": {"company": "Do not save this either."},
        "tool_names": [],
    }

    config = AppConfig.model_validate(config_data)

    assert config.personalization_enabled is False
    assert config.bumblehive["agent"] == {"tool_names": []}


@pytest.mark.asyncio
async def test_disabled_personalization_content_is_not_saved(
    tmp_path: Path,
    config_data: dict[str, object],
) -> None:
    config_data["personalization_enabled"] = False
    bumblehive = config_data["bumblehive"]
    assert isinstance(bumblehive, dict)
    bumblehive["agent"] = {
        "instructions": "Do not persist this.",
        "dynamic_context": {"company": "Do not persist this either."},
    }
    path = tmp_path / "config.json"

    await save_config(path, AppConfig.model_validate(config_data))

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["personalization_enabled"] is False
    assert "instructions" not in saved["bumblehive"]["agent"]
    assert "dynamic_context" not in saved["bumblehive"]["agent"]


def test_inactivity_policy_uses_one_optional_shape(
    config_data: dict[str, object],
) -> None:
    assert AppConfig.model_validate(config_data).inactivity_policy is None

    config_data["inactivity_policy"] = {
        "timeout_seconds": 0.1,
        "max_followups": 3,
    }
    policy = AppConfig.model_validate(config_data).inactivity_policy

    assert policy is not None
    assert policy.timeout_seconds == 0.1
    assert policy.max_followups == 3
    assert policy.on_exhausted == "wait"


@pytest.mark.parametrize(
    "inactivity_policy",
    [
        {"timeout_seconds": 0, "max_followups": 1},
        {"timeout_seconds": 1, "max_followups": 0},
        {"timeout_seconds": 1, "max_followups": 1.5},
        {"timeout_seconds": 1, "max_followups": 1, "on_exhausted": "invalid"},
        {"timeout_seconds": 1, "max_followups": 1, "enabled": True},
    ],
)
def test_invalid_inactivity_policy_is_rejected(
    config_data: dict[str, object],
    inactivity_policy: dict[str, object],
) -> None:
    config_data["inactivity_policy"] = inactivity_policy

    with pytest.raises(ValueError):
        AppConfig.model_validate(config_data)
