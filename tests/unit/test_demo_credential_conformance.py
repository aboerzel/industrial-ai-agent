# DEMO-ONLY CREDENTIALS — NOT FOR PRODUCTION OR SERVICE AUTHENTICATION
"""Narrow browser-demo credential exception never exempts service secrets."""

import runpy
from pathlib import Path

import pytest

CHECKER = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "scripts/check-demo-secrets.py")
)


def test_only_exact_canonical_demo_passwords_are_allowlisted():
    allowed = CHECKER["allowed_demo_password"]
    assert allowed("config/demo-users.toml", "password", "demo-public")
    assert not allowed(".env", "password", "demo-public")
    assert not allowed("compose.yaml", "POSTGRES_PASSWORD", "demo-public")
    assert not allowed(
        "config/demo-users.toml", "password", "synthetic-infrastructure-secret"
    )


@pytest.mark.parametrize(
    "path,key",
    [
        (".env", "POSTGRES_PASSWORD"),
        ("compose.yaml", "MCP_INDUSTRIAL_AGENT_TOKEN"),
        ("config/demo-users.toml", "GROQ_API_KEY"),
        ("frontend/js/app.js", "LANGFUSE_SECRET"),
    ],
)
def test_same_demo_string_is_not_an_infrastructure_secret_exception(path, key):
    assert CHECKER["suspicious"](path, f'{key}="demo-public"')


def test_realistic_provider_secret_pattern_is_detected_even_in_test_files():
    assert CHECKER["suspicious"](
        "tests/unit/synthetic.py", 'key="' + "sk-" + "A" * 32 + '"'
    )
