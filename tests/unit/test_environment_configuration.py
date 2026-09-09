from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SECRET_NAME_MARKERS = ("PASSWORD", "TOKEN", "SECRET", "_KEY", "SALT", "ENCRYPTION")


def test_environment_files_are_structurally_synchronized_without_duplicates() -> None:
    local_path = PROJECT_ROOT / ".env"
    if not local_path.exists():
        pytest.skip("local .env is intentionally unversioned")
    local_sections = _parse_environment_file(local_path)
    example_sections = _parse_environment_file(PROJECT_ROOT / ".env.example")

    assert tuple(local_sections) == tuple(example_sections)
    for section in local_sections:
        assert tuple(local_sections[section]) == tuple(example_sections[section])


def test_environment_example_uses_only_safe_secret_placeholders() -> None:
    example_sections = _parse_environment_file(PROJECT_ROOT / ".env.example")

    for key, value in _flatten(example_sections).items():
        if key == "AGENT_RUNTIME_DATABASE_URL":
            assert "replace-with-" in value
        elif any(marker in key for marker in _SECRET_NAME_MARKERS):
            assert value == "" or value.startswith("replace-with-")


def _parse_environment_file(path: Path) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {}
    current_section: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("# ") and "=" not in line:
            current_section = line
            if current_section in sections:
                raise AssertionError(
                    f"duplicate environment section: {current_section}"
                )
            sections[current_section] = {}
            continue
        if line.startswith("#"):
            continue
        if "=" not in line or current_section is None:
            raise AssertionError("environment entry is missing a section")
        key, value = line.split("=", maxsplit=1)
        if key in _flatten(sections):
            raise AssertionError(f"duplicate environment key: {key}")
        sections[current_section][key] = value
    return sections


def _flatten(sections: dict[str, dict[str, str]]) -> dict[str, str]:
    return {
        key: value for section in sections.values() for key, value in section.items()
    }
