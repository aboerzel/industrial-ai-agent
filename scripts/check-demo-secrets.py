# DEMO-ONLY CREDENTIALS — NOT FOR PRODUCTION OR SERVICE AUTHENTICATION
"""Incremental credential check; only exact predefined browser passwords are public."""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO_FILE = "config/demo-users.toml"
HIGH_SIGNAL = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{20,}|gsk_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})\b|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
)
CREDENTIAL = re.compile(
    r"[\"']?([A-Z][A-Z0-9_]*(?:PASSWORD|TOKEN|SECRET|API_KEY)|password)[\"']?\s*[:=]\s*[\"']([^\"']+)[\"']"
)
ENV_LITERAL = re.compile(r"^([A-Z][A-Z0-9_]*(?:PASSWORD|TOKEN|SECRET|API_KEY))=(.+)$")


def allowed_demo_password(path: str, key: str, value: str) -> bool:
    return (
        path == DEMO_FILE
        and key == "password"
        and value
        in {
            "demo-public",
            "demo-internal",
            "demo-confidential",
            "demo-restricted",
            "demo-admin",
        }
    )


def suspicious(path: str, line: str) -> bool:
    if HIGH_SIGNAL.search(line):
        return True
    for match in (*CREDENTIAL.finditer(line), *ENV_LITERAL.finditer(line)):
        key, value = match.groups()
        if allowed_demo_password(path, key, value):
            continue
        if value.startswith(("replace-with-", "${")):
            continue
        if path.startswith("tests/") and (
            value.startswith(("synthetic-", "fixture-", "test-"))
            or (
                key == "password"
                and value
                in {
                    "demo-public",
                    "demo-internal",
                    "demo-confidential",
                    "demo-restricted",
                    "demo-admin",
                    "incorrect",
                    "wrong",
                    "ungültig",
                }
            )
        ):
            # Deterministic synthetic test inputs, never infrastructure credentials.
            continue
        return True
    return False


def scan_changes() -> list[str]:
    violations = []
    diff = subprocess.run(
        ["git", "diff", "HEAD", "--no-ext-diff", "--unified=0"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    path = ""
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
        elif (
            line.startswith("+")
            and not line.startswith("+++")
            and suspicious(path, line[1:])
        ):
            violations.append(path)
    new_files = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.splitlines()
    for path in new_files:
        try:
            lines = (ROOT / path).read_text(encoding="utf-8").splitlines()
        except UnicodeError:
            continue
        if any(suspicious(path, line) for line in lines):
            violations.append(path)
    data = tomllib.loads((ROOT / DEMO_FILE).read_text(encoding="utf-8"))
    if any(
        not allowed_demo_password(DEMO_FILE, "password", row["password"])
        or row["password"] != row["username"]
        for row in data["users"]
    ):
        violations.append(DEMO_FILE)
    return sorted(set(violations))


if __name__ == "__main__":
    findings = scan_changes()
    print("Incremental secret/credential check: " + ("FAIL" if findings else "PASS"))
    for filename in findings:
        print(filename)  # Only paths, never matched credential values.
    raise SystemExit(bool(findings))
