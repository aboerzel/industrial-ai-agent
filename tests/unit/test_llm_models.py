import pytest

from industrial_ai_agent.agent.llm import ModelProfile


def test_model_profile_normalizes_its_semantic_name() -> None:
    assert ModelProfile(" troubleshooting ").name == "troubleshooting"


def test_model_profile_rejects_empty_name() -> None:
    with pytest.raises(ValueError, match="Model profile name must not be empty"):
        ModelProfile("   ")
