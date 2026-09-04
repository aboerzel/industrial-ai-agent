import os
from pathlib import Path

import pytest

from industrial_ai_agent.infrastructure.local_environment import (
    load_local_environment,
)

SECRET_NAME = "GROQ_API_KEY"


def test_keeps_secret_from_process_environment_when_dotenv_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(SECRET_NAME, "process-value")

    load_local_environment(tmp_path / ".env")

    assert os.environ[SECRET_NAME] == "process-value"


def test_loads_secret_from_dotenv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv(SECRET_NAME, raising=False)
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(f"{SECRET_NAME}=dotenv-value\n", encoding="utf-8")

    load_local_environment(dotenv_path)

    assert os.environ[SECRET_NAME] == "dotenv-value"


def test_process_environment_takes_precedence_over_dotenv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(SECRET_NAME, "process-value")
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(f"{SECRET_NAME}=dotenv-value\n", encoding="utf-8")

    load_local_environment(dotenv_path)

    assert os.environ[SECRET_NAME] == "process-value"
