from pathlib import Path

import pytest
from pydantic import ValidationError

from industrial_ai_agent.agent.model_egress import ExecutionZone
from industrial_ai_agent.agent.model_routing import (
    CostClass,
    LLMCapability,
    QualityClass,
)
from industrial_ai_agent.infrastructure.llm.configuration import (
    AuthenticationMode,
    LLMConfiguration,
    load_llm_configuration,
    local_only_mode_enabled,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_project_configuration() -> LLMConfiguration:
    return load_llm_configuration(PROJECT_ROOT / "config" / "model_profiles.toml")


def test_loads_local_quality_profile() -> None:
    configuration = load_project_configuration()

    profile = configuration.get_profile("local_quality")

    assert profile.provider == "ollama"
    assert profile.model == "qwen3.5:9b"
    assert str(profile.base_url) == "http://localhost:11434/v1"
    assert profile.temperature == 0
    assert profile.authentication is AuthenticationMode.NONE
    assert profile.execution_zone is ExecutionZone.LOCAL
    assert profile.capabilities == frozenset(
        {LLMCapability.TEXT, LLMCapability.TOOL_CALLING}
    )
    assert profile.quality_class is QualityClass.HIGH
    assert profile.cost_class is CostClass.LOW
    assert profile.api_key_env is None


def test_only_live_verified_external_profile_enables_structured_output() -> None:
    configuration = load_project_configuration()

    assert configuration.get_profile("mistral_fast").supports_structured_output is False
    assert (
        configuration.get_profile("nvidia_quality").supports_structured_output is True
    )


def test_loads_local_fast_profile() -> None:
    profile = load_project_configuration().get_profile("local_fast")

    assert profile.provider == "ollama"
    assert profile.model == "qwen3.5:4b"
    assert str(profile.base_url) == "http://localhost:11434/v1"
    assert profile.temperature == 0
    assert profile.authentication is AuthenticationMode.NONE
    assert profile.execution_zone is ExecutionZone.LOCAL
    assert profile.capabilities == frozenset(
        {LLMCapability.TEXT, LLMCapability.TOOL_CALLING}
    )
    assert profile.quality_class is QualityClass.STANDARD
    assert profile.cost_class is CostClass.LOW
    assert profile.api_key_env is None


def test_loads_public_fast_profile() -> None:
    profile = load_project_configuration().get_profile("public_fast")

    assert profile.provider == "groq"
    assert profile.model == "openai/gpt-oss-20b"
    assert str(profile.base_url) == "https://api.groq.com/openai/v1"
    assert profile.temperature == 0
    assert profile.authentication is AuthenticationMode.API_KEY
    assert profile.execution_zone is ExecutionZone.PUBLIC_CLOUD
    assert profile.capabilities == frozenset(
        {LLMCapability.TEXT, LLMCapability.TOOL_CALLING}
    )
    assert profile.quality_class is QualityClass.HIGH
    assert profile.cost_class is CostClass.LOW
    assert profile.api_key_env == "GROQ_API_KEY"


@pytest.mark.parametrize(
    ("profile_name", "provider", "model", "base_url", "api_key_env"),
    (
        (
            "mistral_fast",
            "mistral",
            "mistral-small-latest",
            "https://api.mistral.ai/v1",
            "MISTRAL_API_KEY",
        ),
        (
            "nvidia_quality",
            "nvidia",
            "nvidia/nemotron-3.5-lightning-30b-a3b",
            "https://integrate.api.nvidia.com/v1",
            "NVIDIA_API_KEY",
        ),
    ),
)
def test_loads_external_openai_compatible_provider_profiles(
    profile_name: str,
    provider: str,
    model: str,
    base_url: str,
    api_key_env: str,
) -> None:
    profile = load_project_configuration().get_profile(profile_name)

    assert profile.provider == provider
    assert profile.model == model
    assert str(profile.base_url) == base_url
    assert profile.api_key_env == api_key_env
    assert profile.execution_zone is ExecutionZone.PUBLIC_CLOUD
    assert profile.capabilities == frozenset(
        {LLMCapability.TEXT, LLMCapability.TOOL_CALLING}
    )


def test_docker_configuration_includes_nvidia_quality_profile() -> None:
    configuration = load_llm_configuration(
        PROJECT_ROOT / "config" / "model_profiles.docker.toml"
    )

    profile = configuration.get_profile("nvidia_quality")

    assert profile.provider == "nvidia"
    assert profile.model == "nvidia/nemotron-3.5-lightning-30b-a3b"
    assert str(profile.base_url) == "https://integrate.api.nvidia.com/v1"
    assert profile.api_key_env == "NVIDIA_API_KEY"
    assert profile.supports_structured_output is True
    assert profile.max_output_tokens == 256


def test_nvidia_profile_has_a_bounded_agent_output_budget() -> None:
    configuration = load_project_configuration()

    assert configuration.get_profile("nvidia_quality").max_output_tokens == 256


@pytest.mark.parametrize(
    ("environment", "expected_profiles"),
    (
        ({}, {"local_fast", "local_quality"}),
        (
            {"MISTRAL_API_KEY": "mistral-key"},
            {"local_fast", "local_quality", "mistral_fast"},
        ),
        (
            {"NVIDIA_API_KEY": "nvidia-key"},
            {"local_fast", "local_quality", "nvidia_quality"},
        ),
    ),
)
def test_only_configured_authenticated_profiles_are_routing_candidates(
    environment: dict[str, str], expected_profiles: set[str]
) -> None:
    configuration = load_project_configuration()

    profiles = configuration.get_available_routing_profiles(environment=environment)

    assert {profile.profile.name for profile in profiles} == expected_profiles


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


def test_local_only_mode_accepts_only_explicit_boolean_values(monkeypatch) -> None:
    monkeypatch.setenv("LOCAL_ONLY_MODE", "true")
    assert local_only_mode_enabled() is True

    monkeypatch.setenv("LOCAL_ONLY_MODE", "false")
    assert local_only_mode_enabled() is False

    monkeypatch.setenv("LOCAL_ONLY_MODE", "unexpected")
    with pytest.raises(ValueError, match="LOCAL_ONLY_MODE"):
        local_only_mode_enabled()


def test_rejects_unknown_profile() -> None:
    configuration = LLMConfiguration(profiles={})

    with pytest.raises(ValueError, match="Unknown model profile: planning"):
        configuration.get_profile("planning")


def test_rejects_api_key_value_in_model_configuration() -> None:
    with pytest.raises(ValidationError, match="api_key"):
        LLMConfiguration.model_validate(
            {
                "profiles": {
                    "local_quality": {
                        "provider": "ollama",
                        "model": "qwen3.5:9b",
                        "base_url": "http://localhost:11434/v1",
                        "temperature": 0,
                        "authentication": "none",
                        "execution_zone": "LOCAL",
                        "max_data_classification": "RESTRICTED",
                        "capabilities": ["TEXT", "TOOL_CALLING"],
                        "quality_class": "HIGH",
                        "cost_class": "LOW",
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
                    "local_quality": {
                        "provider": "cloud-provider",
                        "model": "cloud-model",
                        "base_url": "https://llm.example.com/v1",
                        "temperature": 0,
                        "authentication": "api_key",
                        "execution_zone": "PUBLIC_CLOUD",
                        "max_data_classification": "CONFIDENTIAL",
                        "capabilities": ["TEXT"],
                        "quality_class": "HIGH",
                        "cost_class": "LOW",
                    }
                }
            }
        )


def test_rejects_environment_variable_name_for_no_authentication() -> None:
    with pytest.raises(ValidationError, match="api_key_env must not be set"):
        LLMConfiguration.model_validate(
            {
                "profiles": {
                    "local_quality": {
                        "provider": "ollama",
                        "model": "qwen3.5:9b",
                        "base_url": "http://localhost:11434/v1",
                        "temperature": 0,
                        "authentication": "none",
                        "execution_zone": "LOCAL",
                        "max_data_classification": "RESTRICTED",
                        "capabilities": ["TEXT", "TOOL_CALLING"],
                        "quality_class": "HIGH",
                        "cost_class": "LOW",
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
                    "local_quality": {
                        "provider": "ollama",
                        "model": "qwen3.5:9b",
                        "base_url": "http://localhost:11434/v1",
                        "temperature": 0,
                        "authentication": "none",
                        "capabilities": ["TEXT", "TOOL_CALLING"],
                        "quality_class": "HIGH",
                        "cost_class": "LOW",
                    }
                }
            }
        )


def test_requires_explicit_maximum_data_classification() -> None:
    with pytest.raises(ValidationError, match="max_data_classification"):
        LLMConfiguration.model_validate(
            {
                "profiles": {
                    "local_quality": {
                        "provider": "ollama",
                        "model": "qwen3.5:9b",
                        "base_url": "http://localhost:11434/v1",
                        "temperature": 0,
                        "authentication": "none",
                        "execution_zone": "LOCAL",
                        "capabilities": ["TEXT", "TOOL_CALLING"],
                        "quality_class": "HIGH",
                        "cost_class": "LOW",
                    }
                }
            }
        )


def test_rejects_invalid_maximum_data_classification() -> None:
    with pytest.raises(ValidationError, match="maximum data classification"):
        LLMConfiguration.model_validate(
            {
                "profiles": {
                    "local_quality": {
                        "provider": "ollama",
                        "model": "qwen3.5:9b",
                        "base_url": "http://localhost:11434/v1",
                        "temperature": 0,
                        "authentication": "none",
                        "execution_zone": "LOCAL",
                        "max_data_classification": "TOP_SECRET",
                        "capabilities": ["TEXT", "TOOL_CALLING"],
                        "quality_class": "HIGH",
                        "cost_class": "LOW",
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
                        "capabilities": ["TEXT", "TOOL_CALLING"],
                        "quality_class": "HIGH",
                        "cost_class": "LOW",
                    }
                }
            }
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("capabilities", ["UNKNOWN"]),
        ("quality_class", "UNKNOWN"),
        ("cost_class", "UNKNOWN"),
    ],
)
def test_rejects_unknown_routing_metadata(field: str, value: object) -> None:
    raw_profile: dict[str, object] = {
        "provider": "ollama",
        "model": "qwen3.5:9b",
        "base_url": "http://localhost:11434/v1",
        "temperature": 0,
        "authentication": "none",
        "execution_zone": "LOCAL",
        "capabilities": ["TEXT", "TOOL_CALLING"],
        "quality_class": "HIGH",
        "cost_class": "LOW",
        field: value,
    }

    with pytest.raises(ValidationError, match=field):
        LLMConfiguration.model_validate({"profiles": {"local_quality": raw_profile}})
