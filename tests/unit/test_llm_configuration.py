from pathlib import Path

import pytest
from pydantic import ValidationError

from industrial_ai_agent.infrastructure.llm.configuration import (
    AuthenticationMode,
    LLMConfiguration,
    load_llm_configuration,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_loads_troubleshooting_profile() -> None:
    configuration = load_llm_configuration(
        PROJECT_ROOT / "config" / "model_profiles.toml"
    )

    profile = configuration.get_profile("troubleshooting")

    assert profile.provider == "ollama"
    assert profile.model == "qwen3.5:9b"
    assert str(profile.base_url) == "http://localhost:11434/v1"
    assert profile.temperature == 0
    assert profile.authentication is AuthenticationMode.NONE
    assert profile.api_key_env is None


def test_rejects_unknown_profile() -> None:
    configuration = LLMConfiguration(profiles={})

    with pytest.raises(ValueError, match="Unknown model profile: planning"):
        configuration.get_profile("planning")


def test_rejects_api_key_value_in_model_configuration() -> None:
    with pytest.raises(ValidationError, match="api_key"):
        LLMConfiguration.model_validate(
            {
                "profiles": {
                    "troubleshooting": {
                        "provider": "ollama",
                        "model": "qwen3.5:9b",
                        "base_url": "http://localhost:11434/v1",
                        "temperature": 0,
                        "authentication": "none",
                        "api_key": "must-not-be-configured-here",
                    }
                }
            }
        )


def test_requires_environment_variable_name_for_api_key_authentication() -> None:
    with pytest.raises(ValidationError, match="api_key_env is required"):
        LLMConfiguration.model_validate(
            {
                "profiles": {
                    "troubleshooting": {
                        "provider": "cloud-provider",
                        "model": "cloud-model",
                        "base_url": "https://llm.example.com/v1",
                        "temperature": 0,
                        "authentication": "api_key",
                    }
                }
            }
        )


def test_rejects_environment_variable_name_for_no_authentication() -> None:
    with pytest.raises(ValidationError, match="api_key_env must not be set"):
        LLMConfiguration.model_validate(
            {
                "profiles": {
                    "troubleshooting": {
                        "provider": "ollama",
                        "model": "qwen3.5:9b",
                        "base_url": "http://localhost:11434/v1",
                        "temperature": 0,
                        "authentication": "none",
                        "api_key_env": "UNNECESSARY_API_KEY",
                    }
                }
            }
        )
