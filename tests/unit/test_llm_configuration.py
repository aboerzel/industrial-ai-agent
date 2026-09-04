from pathlib import Path

import pytest
from pydantic import ValidationError

from industrial_ai_agent.agent.model_egress import ExecutionZone
from industrial_ai_agent.infrastructure.llm.configuration import (
    AuthenticationMode,
    LLMConfiguration,
    load_llm_configuration,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_project_configuration() -> LLMConfiguration:
    return load_llm_configuration(PROJECT_ROOT / "config" / "model_profiles.toml")


def test_loads_troubleshooting_profile() -> None:
    configuration = load_project_configuration()

    profile = configuration.get_profile("troubleshooting")

    assert profile.provider == "ollama"
    assert profile.model == "qwen3.5:9b"
    assert str(profile.base_url) == "http://localhost:11434/v1"
    assert profile.temperature == 0
    assert profile.authentication is AuthenticationMode.NONE
    assert profile.execution_zone is ExecutionZone.LOCAL
    assert profile.api_key_env is None


def test_loads_local_fast_profile() -> None:
    profile = load_project_configuration().get_profile("local_fast")

    assert profile.provider == "ollama"
    assert profile.model == "qwen3.5:4b"
    assert str(profile.base_url) == "http://localhost:11434/v1"
    assert profile.temperature == 0
    assert profile.authentication is AuthenticationMode.NONE
    assert profile.execution_zone is ExecutionZone.LOCAL
    assert profile.api_key_env is None


def test_loads_local_quality_profile() -> None:
    profile = load_project_configuration().get_profile("local_quality")

    assert profile.provider == "ollama"
    assert profile.model == "qwen3.5:9b"
    assert str(profile.base_url) == "http://localhost:11434/v1"
    assert profile.temperature == 0
    assert profile.authentication is AuthenticationMode.NONE
    assert profile.execution_zone is ExecutionZone.LOCAL
    assert profile.api_key_env is None


def test_loads_public_fast_profile() -> None:
    profile = load_project_configuration().get_profile("public_fast")

    assert profile.provider == "groq"
    assert profile.model == "openai/gpt-oss-20b"
    assert str(profile.base_url) == "https://api.groq.com/openai/v1"
    assert profile.temperature == 0
    assert profile.authentication is AuthenticationMode.API_KEY
    assert profile.execution_zone is ExecutionZone.PUBLIC_CLOUD
    assert profile.api_key_env == "GROQ_API_KEY"


def test_local_profiles_use_different_models() -> None:
    configuration = load_project_configuration()

    fast_profile = configuration.get_profile("local_fast")
    quality_profile = configuration.get_profile("local_quality")

    assert fast_profile.model != quality_profile.model


def test_local_profiles_use_same_endpoint() -> None:
    configuration = load_project_configuration()

    fast_profile = configuration.get_profile("local_fast")
    quality_profile = configuration.get_profile("local_quality")

    assert fast_profile.base_url == quality_profile.base_url


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
                        "execution_zone": "LOCAL",
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
                        "execution_zone": "PUBLIC_CLOUD",
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
                        "execution_zone": "LOCAL",
                        "api_key_env": "UNNECESSARY_API_KEY",
                    }
                }
            }
        )


def test_requires_explicit_execution_zone() -> None:
    with pytest.raises(ValidationError, match="execution_zone"):
        LLMConfiguration.model_validate(
            {
                "profiles": {
                    "troubleshooting": {
                        "provider": "ollama",
                        "model": "qwen3.5:9b",
                        "base_url": "http://localhost:11434/v1",
                        "temperature": 0,
                        "authentication": "none",
                    }
                }
            }
        )


def test_rejects_unknown_execution_zone() -> None:
    with pytest.raises(ValidationError, match="execution_zone"):
        LLMConfiguration.model_validate(
            {
                "profiles": {
                    "troubleshooting": {
                        "provider": "ollama",
                        "model": "qwen3.5:9b",
                        "base_url": "http://localhost:11434/v1",
                        "temperature": 0,
                        "authentication": "none",
                        "execution_zone": "UNKNOWN",
                    }
                }
            }
        )
