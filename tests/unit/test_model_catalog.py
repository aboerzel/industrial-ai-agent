from pathlib import Path

import pytest

from industrial_ai_agent.agent.model_egress import ExecutionZone
from industrial_ai_agent.agent.model_selection import ModelCapability
from industrial_ai_agent.infrastructure.llm.configuration import (
    ModelCatalogConfiguration,
    load_model_catalog,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_catalog_uses_stable_ids_and_contains_no_routing_configuration() -> None:
    path = PROJECT_ROOT / "config" / "model_catalog.toml"
    catalog = load_model_catalog(path)
    raw = path.read_text(encoding="utf-8")

    assert {model.model_id.value for model in catalog.list_models()} == {
        "local_fast",
        "local_quality",
        "groq_benchmark",
        "mistral_fast",
        "nvidia_quality",
    }
    assert "automatic_routing" not in raw
    assert "max_data_classification" in raw
    assert "default" not in raw
    assert "[profiles." not in raw


def test_catalog_display_name_is_not_a_lookup_identity() -> None:
    catalog = load_model_catalog(PROJECT_ROOT / "config" / "model_catalog.toml")

    model = catalog.get_model("nvidia_quality")

    assert model.display_name == "NVIDIA Nemotron 3.5 Lightning"
    assert model.execution_zone is ExecutionZone.PUBLIC_CLOUD
    assert ModelCapability.STRUCTURED_OUTPUT in model.capabilities
    with pytest.raises(ValueError, match="Unknown model ID"):
        catalog.get_model(model.display_name)


def test_groq_catalog_preserves_individual_capabilities_and_declares_only_combination_limit() -> (
    None
):
    catalog = load_model_catalog(PROJECT_ROOT / "config" / "model_catalog.toml")

    groq = catalog.get_model("groq_benchmark")

    assert groq.capabilities == frozenset(
        {
            ModelCapability.TEXT,
            ModelCapability.TOOL_CALLING,
            ModelCapability.STRUCTURED_OUTPUT,
        }
    )
    assert groq.incompatible_capability_combinations == frozenset(
        {frozenset({ModelCapability.TOOL_CALLING, ModelCapability.STRUCTURED_OUTPUT})}
    )


def test_catalog_rejects_impossible_capability_combination_constraint() -> None:
    model = {
        "id": "external",
        "display_name": "External",
        "provider": "test",
        "provider_model": "test/model",
        "base_url": "https://example.test/v1",
        "temperature": 0,
        "authentication": "none",
        "execution_zone": "LOCAL",
        "max_data_classification": "RESTRICTED",
        "capabilities": ["text"],
        "incompatible_capability_combinations": [["text", "tool_calling"]],
        "quality_class": "STANDARD",
        "cost_class": "LOW",
    }

    with pytest.raises(ValueError, match="must be supported individually"):
        ModelCatalogConfiguration.model_validate({"models": [model]})


def test_docker_catalog_is_pure_and_uses_container_local_endpoint() -> None:
    path = PROJECT_ROOT / "config" / "model_catalog.docker.toml"
    catalog = load_model_catalog(path)

    assert str(catalog.get_model_config("local_quality").base_url) == (
        "http://host.docker.internal:11434/v1"
    )
    assert "automatic_routing" not in path.read_text(encoding="utf-8")
    assert catalog.get_model("mistral_fast").display_name == "Mistral Small"


def test_catalog_rejects_routing_fields_and_embedded_credentials() -> None:
    model = {
        "id": "external",
        "display_name": "External",
        "provider": "test",
        "provider_model": "test/model",
        "base_url": "https://example.test/v1",
        "temperature": 0,
        "authentication": "api_key",
        "api_key_env": "TEST_API_KEY",
        "execution_zone": "PUBLIC_CLOUD",
        "max_data_classification": "CONFIDENTIAL",
        "capabilities": ["text"],
        "quality_class": "STANDARD",
        "cost_class": "LOW",
    }

    with pytest.raises(ValueError):
        ModelCatalogConfiguration.model_validate(
            {"models": [{**model, "automatic_routing": True}]}
        )
    with pytest.raises(ValueError):
        ModelCatalogConfiguration.model_validate(
            {"models": [{**model, "api_key": "secret"}]}
        )


def test_api_key_authentication_requires_environment_variable_name() -> None:
    with pytest.raises(ValueError, match="api_key_env"):
        ModelCatalogConfiguration.model_validate(
            {
                "models": [
                    {
                        "id": "external",
                        "display_name": "External",
                        "provider": "test",
                        "provider_model": "test/model",
                        "base_url": "https://example.test/v1",
                        "temperature": 0,
                        "authentication": "api_key",
                        "execution_zone": "PUBLIC_CLOUD",
                        "max_data_classification": "CONFIDENTIAL",
                        "capabilities": ["text"],
                        "quality_class": "STANDARD",
                        "cost_class": "LOW",
                    }
                ]
            }
        )


def test_catalog_static_availability_requires_configured_api_key() -> None:
    catalog = load_model_catalog(PROJECT_ROOT / "config" / "model_catalog.toml")

    assert catalog.is_model_available("local_quality", environment={})
    assert not catalog.is_model_available("nvidia_quality", environment={})
    assert catalog.is_model_available(
        "nvidia_quality", environment={"NVIDIA_API_KEY": "configured-key"}
    )
