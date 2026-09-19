import pytest

from industrial_ai_agent.agent.llm import ModelId


def test_model_id_normalizes_its_stable_value() -> None:
    assert ModelId(" local_quality ").value == "local_quality"


def test_model_id_rejects_empty_value() -> None:
    with pytest.raises(ValueError, match="Model ID must not be empty"):
        ModelId("   ")
