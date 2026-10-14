from pathlib import Path

import pytest

from industrial_ai_agent.infrastructure.persistence import demo_seed


def test_missing_external_factory_metadata_fails_without_a_path_leak(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(demo_seed, "FACTORY_DATA_ROOT", tmp_path / "missing")

    with pytest.raises(
        RuntimeError,
        match="FACTORY_DATA_ROOT does not provide document catalog metadata",
    ) as error:
        demo_seed._seed_document_catalog(object())

    assert str(tmp_path) not in str(error.value)


def test_seed_visibility_matrix_has_stable_identifiers_at_every_level() -> None:
    from industrial_ai_agent.agent.run_classification_policy import (
        AgentRunClassificationPolicy,
    )
    from industrial_ai_agent.domain.security import DataClassification

    assert set(demo_seed.STATION_CLASSIFICATIONS) == set(demo_seed.STATIONS)
    for level in DataClassification:
        stations = [
            code
            for code, label in demo_seed.STATION_CLASSIFICATIONS.items()
            if label == int(level)
        ]
        products = [
            code
            for code in demo_seed.PRODUCTS
            if demo_seed._product_classification(code) == int(level)
        ]
        assert len(stations) >= 2
        assert len(products) >= 2
        for code in stations + products:
            assert (
                AgentRunClassificationPolicy().resolve_request(code).data_classification
                == level
            )
