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
