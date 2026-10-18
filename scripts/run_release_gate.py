"""Explicit software verification and separate real local-runtime qualification."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.release_contract import SOFTWARE_GATES, overall, software_result
from scripts.release_runtime import release_plan, runtime_qualification
from scripts.release_support import (
    disposable_database,
    docker,
    knowledge_deployment_environment,
    software_browser_environment,
    wait_container_health,
)


def save(path, body):
    temp = path.with_suffix(".next")
    temp.write_text(json.dumps(body, indent=2), encoding="utf-8")
    temp.replace(path)


def baseline():
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    paths = set(result.stdout.decode().split("\0")) | {".env"}
    manifest = {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in sorted(paths)
        if name and not name.startswith("docs/reviews/") and (ROOT / name).is_file()
    }
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {
        "branch": branch,
        "head": revision,
        "files": manifest,
        "fingerprint": hashlib.sha256(
            json.dumps(manifest, sort_keys=True).encode()
        ).hexdigest(),
    }


def execute(command, evidence, name, *, env=None, cwd=ROOT):
    print(f"START {name}", flush=True)
    started = time.monotonic()
    with (evidence / f"{name}.log").open("x", encoding="utf-8") as log:
        result = subprocess.run(
            command, check=False, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT
        )
    print(
        f"END {name} exit={result.returncode} duration={time.monotonic() - started:.3f}s",
        flush=True,
    )
    return result.returncode


def junit_result(path, code):
    cases = list(ET.parse(path).getroot().iter("testcase"))
    skips = [
        {
            "test": c.attrib.get("classname", "") + "." + c.attrib["name"],
            "reason": c.find("skipped").attrib.get("message", ""),
        }
        for c in cases
        if c.find("skipped") is not None
    ]
    allowed = lambda s: (
        (
            bool(
                re.fullmatch(
                    r"tests\.integration\.test_knowledge_container_runtime\.test_kdep_0[1-5]_[a-z_]+",
                    s["test"],
                )
            )
            and s["reason"]
            == "KDEP requires an explicit clean image and isolated offline deployment"
        )
        or (
            s["test"]
            == "tests.unit.test_document_content_storage.test_catalog_content_path_rejects_symlink_escape_and_missing_storage"
            and s["reason"] == "symlink creation is unavailable on this platform"
        )
    )
    unexplained = sum(not allowed(s) for s in skips)
    failed = sum(
        c.find("failure") is not None or c.find("error") is not None for c in cases
    )
    return {
        "status": "PASS"
        if code == 0 and cases and not failed and not unexplained
        else "FAIL",
        "collected": len(cases),
        "passed": len(cases) - failed - len(skips),
        "failed": failed,
        "skipped": skips,
        "unexplained_skips": unexplained,
    }


def pytest_gate(evidence, name, paths, *, env=None):
    xml = evidence / f"{name}.xml"
    code = execute(
        [
            sys.executable,
            "-m",
            "pytest",
            *paths,
            "-q",
            "--tb=short",
            f"--junitxml={xml}",
        ],
        evidence,
        name,
        env={**(env or os.environ), "PYTEST_ADDOPTS": ""},
    )
    return junit_result(xml, code)


def clean_build(evidence):
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
    composition = json.loads(docker("compose", "config", "--format", "json"))
    applications = {
        name: body
        for name, body in composition["services"].items()
        if body.get("build")
    }
    if not applications:
        raise RuntimeError("No project application build targets discovered")
    if execute(["docker", "compose", "down"], evidence, "stack-stop"):
        return {"status": "FAIL", "reason": "STACK_STOP_FAILED"}
    code = execute(
        ["docker", "compose", "build", "--no-cache"], evidence, "clean-build"
    )
    # Restore supported stack even after a failed build, retaining first build evidence.
    start_code = execute(["docker", "compose", "up", "-d"], evidence, "stack-start")
    images = {}
    for name in applications:
        image = docker("compose", "images", "-q", name).strip()
        images[name] = (
            json.loads(docker("image", "inspect", image))[0]["Id"] if image else None
        )
    states = [
        json.loads(line)
        for line in docker("compose", "ps", "--format", "json").splitlines()
        if line.strip()
    ]
    # Real-model-dependent startup readiness is evidence for runtime, never software.
    # The isolated deterministic deployment gate below verifies the application image.
    return {
        "status": "PASS" if code == 0 and all(images.values()) else "FAIL",
        "images": images,
        "images_built": len(images) if code == 0 else 0,
        "images_required": len(applications),
        "production_start_exit": start_code,
        "services_healthy_at_start": sum(s["Health"] == "healthy" for s in states),
        "services_required": len(composition["services"]),
    }


def fast_gate(evidence):
    xml = evidence / "fast-unit.xml"
    code = execute(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "scripts/run-quality-gate.ps1",
            "FAST",
        ],
        evidence,
        "fast",
        env={**os.environ, "PYTEST_ADDOPTS": f'--junitxml="{xml.as_posix()}"'},
    )
    units = junit_result(xml, 0)
    return {
        "status": "PASS" if code == 0 and units["status"] == "PASS" else "FAIL",
        "units": units,
        "unexplained_skips": units["unexplained_skips"],
    }


def software_verification(evidence, run_id):
    gates = {name: {"status": "NOT_RUN"} for name in sorted(SOFTWARE_GATES)}

    def gate(name, operation):
        try:
            gates[name] = operation()
        except Exception as error:  # noqa: BLE001 - retain failure and continue independent gates.
            gates[name] = {"status": "FAIL", "error_type": type(error).__name__}
        save(
            evidence / "software-progress.json",
            {"gates": gates, "result": software_result(gates)},
        )
        print(f"GATE {name}: {gates[name]['status']}", flush=True)

    gate("clean_build", lambda: clean_build(evidence))
    for name, paths in (("backend", ["tests"]), ("integration", ["tests/integration"])):

        def database_tests(name=name, paths=paths):
            with disposable_database() as (env, _):
                return pytest_gate(evidence, name, paths, env=env)

        gate(name, database_tests)
    gate("fast", lambda: fast_gate(evidence))
    gate(
        "frontend",
        lambda: {
            "status": "PASS"
            if execute(
                ["node", "--test", "../tests/frontend/*.test.mjs"],
                evidence,
                "frontend",
                cwd=ROOT / "frontend",
            )
            == 0
            else "FAIL"
        },
    )

    def kdep():
        with knowledge_deployment_environment(evidence) as (env, container):
            result = pytest_gate(
                evidence,
                "kdep",
                ["tests/integration/test_knowledge_container_runtime.py"],
                env=env,
            )
            if result["collected"] != 5 or result["skipped"]:
                result["status"] = "FAIL"
            if result["status"] == "PASS":
                docker("restart", container)
                wait_container_health(container)
                result["offline_restart"] = pytest_gate(
                    evidence,
                    "kdep-offline-restart",
                    [
                        "tests/integration/test_knowledge_container_runtime.py::test_kdep_04_mcp_retrieval_preserves_fixture_provenance_and_clearance"
                    ],
                    env=env,
                )
                if result["offline_restart"]["status"] != "PASS":
                    result["status"] = "FAIL"
            result["embedding_transport"] = (
                "TEST_ONLY_DETERMINISTIC; real cached OCR/layout/reranker and production image"
            )
            return result

    gate("kdep", kdep)
    try:
        with software_browser_environment(evidence) as env:
            plan = release_plan()

            def agent():
                code = execute(
                    [
                        "node",
                        "scripts/run-e2e-journey.mjs",
                        "--all",
                        "--run-id",
                        run_id,
                    ],
                    evidence,
                    "deterministic-agent",
                    env=env,
                    cwd=ROOT / "frontend",
                )
                artifacts = [
                    json.loads(
                        (
                            ROOT
                            / "evals/results/browser-e2e"
                            / run_id
                            / f"journey-{item['id']}.json"
                        ).read_text(encoding="utf-8")
                    )
                    for item in plan
                ]
                expected = sum(
                    a["requirement"] == "REQUIRED"
                    for item in plan
                    for a in item["assertions"]
                )
                passed = sum(
                    item["assertion_summary"]["required_passed"] for item in artifacts
                )
                valid = all(
                    item["status"] == "PASS"
                    and item["metadata"]["execution_mode"] == "SOFTWARE_DETERMINISTIC"
                    for item in artifacts
                )
                return {
                    "status": "PASS"
                    if code == 0 and valid and passed == expected
                    else "FAIL",
                    "journeys": len(artifacts),
                    "passed_journeys": sum(a["status"] == "PASS" for a in artifacts),
                    "required_assertions": expected,
                    "passed_assertions": passed,
                    "provider": "TEST_ONLY_SCRIPTED_WIRE",
                }

            gate("deterministic_agent_e2e", agent)
            before = set((ROOT / "evals/results/browser-e2e").glob("legacy-*"))

            def legacy():
                code = execute(
                    [
                        "node",
                        "node_modules/@playwright/test/cli.js",
                        "test",
                        "-c",
                        "playwright.config.mjs",
                        "--retries=0",
                    ],
                    evidence,
                    "legacy-browser",
                    env=env,
                    cwd=ROOT / "frontend",
                )
                directories = (
                    set((ROOT / "evals/results/browser-e2e").glob("legacy-*")) - before
                )
                reports = [
                    directory / "journeys.json"
                    for directory in directories
                    if (directory / "journeys.json").is_file()
                ]
                assert len(reports) == 1, (
                    "Expected exactly one new controller aggregate"
                )
                report = json.loads(reports[0].read_text(encoding="utf-8"))
                required = [
                    a
                    for j in report["journeys"]
                    for a in j["assertions"]
                    if a["requirement"] == "REQUIRED"
                ]
                complete = (
                    len(report["journeys"]) == 5
                    and len(required) == 30
                    and all(a["status"] == "PASS" and a["executed"] for a in required)
                )
                return {
                    "status": "PASS"
                    if code == 0 and complete and report["execution_status"] == "PASS"
                    else "FAIL",
                    "report": report,
                }

            gate("legacy_browser", legacy)
            refs = evidence / "reference-contracts"
            browser_env = {
                **env,
                "REFERENCE_LIVE_URL": "",
                "REFERENCE_SOFTWARE_URL": env["E2E_FRONTEND_URL"],
                "REFERENCE_EVIDENCE_DIR": str(refs),
                "PLAYWRIGHT_JSON_OUTPUT_FILE": str(evidence / "safe-browser.json"),
            }
            gate("safe_browser", lambda: browser_gate(evidence, browser_env))

            def references():
                rows = json.loads(
                    (refs / "reference-browser-matrix.json").read_text(encoding="utf-8")
                )
                valid = (
                    len(rows) == 30
                    and {r["index"] for r in rows} == set(range(1, 31))
                    and all(
                        r["software_backend"]
                        and r["http_status"] == 200
                        and r["outcome"]["status"] == "success"
                        and r["outcome"]["tool_calls"][0]["tool"] == r["tool"]
                        and r["outcome"]["tool_calls"][0]["arguments"][r["argument"]]
                        == r["value"]
                        for r in rows
                    )
                )
                return {
                    "status": "PASS"
                    if valid and gates["safe_browser"]["status"] == "PASS"
                    else "FAIL",
                    "original_actions": min(len(rows), 16),
                    "extended_actions": len(rows),
                    "persistence_authorization_and_document_controls": "safe_browser",
                }

            gate("reference_contracts", references)
    except Exception as error:  # noqa: BLE001 - startup failures must remain explicit software failures.
        for name in (
            "deterministic_agent_e2e",
            "legacy_browser",
            "safe_browser",
            "reference_contracts",
        ):
            if gates[name]["status"] == "NOT_RUN":
                gates[name] = {"status": "FAIL", "error_type": type(error).__name__}

    def historical():
        required = ("backend", "integration", "frontend", "safe_browser")
        return {
            "status": "PASS"
            if all(gates[name]["status"] == "PASS" for name in required)
            else "FAIL",
            "coverage": "Complete backend, integration, frontend and browser regressions including C01-C06/R01-R06/N01/FC01-FC04/CERT-01; no inherited historical status",
        }

    gate("historical_findings", historical)
    return {
        "result": software_result(gates),
        "gates": gates,
        "unexplained_skips": sum(g.get("unexplained_skips", 0) for g in gates.values()),
    }


def browser_gate(evidence, env):
    code = execute(
        [
            "node",
            "node_modules/@playwright/test/cli.js",
            "test",
            "-c",
            "playwright.fixtures.config.mjs",
            "--retries=0",
            "--reporter=list,json",
            "--output",
            str(evidence / "safe-browser-artifacts"),
        ],
        evidence,
        "safe-browser",
        env=env,
        cwd=ROOT / "frontend",
    )
    report = json.loads((evidence / "safe-browser.json").read_text(encoding="utf-8"))
    stats = report["stats"]
    valid = (
        code == 0
        and stats["unexpected"] == stats["skipped"] == stats["flaky"] == 0
        and stats["expected"] > 0
    )
    return {
        "status": "PASS" if valid else "FAIL",
        **stats,
        "unexplained_skips": stats["skipped"],
    }


def render(report):
    software, runtime = (
        report["software_verification"],
        report["local_runtime_qualification"],
    )
    rows = ["# Release verification", "", "## SOFTWARE VERIFICATION", ""]
    labels = {
        "clean_build": "Clean build",
        "backend": "Backend",
        "integration": "Integration",
        "kdep": "KDEP",
        "fast": "FAST",
        "frontend": "Frontend",
        "safe_browser": "Safe Browser",
        "legacy_browser": "Legacy Browser",
        "deterministic_agent_e2e": "Deterministic Agent E2E",
        "reference_contracts": "Reference contracts",
        "historical_findings": "Historical findings",
    }
    rows += [
        f"{labels[key]}: {value['status']}"
        for key, value in software.get("gates", {}).items()
    ]
    rows += [
        f"Result: {software['result']}",
        "",
        "## LOCAL AI RUNTIME QUALIFICATION",
        "",
        "Provider: Ollama",
        "Model: qwen3.5:9b",
        f"Preflight: {runtime.get('preflight', 'NOT_TESTED')}",
        f"Real-model gate: {runtime.get('gate', 'NOT_TESTED')}",
        f"Reason: {runtime.get('reason_code') or 'NONE'}",
        f"Provider timeouts: {runtime.get('provider_timeouts', 'NOT_TESTED')}",
        f"Ollama 500: {runtime.get('ollama_http_500', 'NOT_TESTED')}",
        f"Result: {runtime['result']}",
        "",
        "\n".join(
            [
                "| Journey | Classification | Required passed | Required total |",
                "|---|---|---:|---:|",
                *[
                    f"| {item['id']} | {item['classification']} | {item['required_passed']} | {item['required_total']} |"
                    for item in runtime.get("tests", [])
                ],
            ]
        ),
        "",
        "## OVERALL",
        "",
        f"Software correctness verified: {report['overall']['software_correctness_verified']}",
        f"Local model runtime qualified: {report['overall']['local_model_runtime_qualified']}",
        "",
        "A software PASS alone does not qualify the complete deployment.",
        "",
    ]
    return "\n\n".join(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tier", choices=("SOFTWARE", "LOCAL_RUNTIME", "FULL"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    run_id = "release-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:8]
    evidence = args.output or ROOT / "evals/results/release-verification" / run_id
    evidence.mkdir(parents=True, exist_ok=False)
    initial = baseline()
    save(evidence / "baseline-initial.json", initial)
    software, runtime = {"result": "NOT_TESTED"}, {"result": "NOT_TESTED"}
    active = "software"
    try:
        if args.tier in {"SOFTWARE", "FULL"}:
            software = software_verification(evidence, run_id + "-software")
        if args.tier in {"LOCAL_RUNTIME", "FULL"}:
            active = "runtime"
            runtime = runtime_qualification(
                evidence / "local-runtime", run_id + "-runtime"
            )
    except Exception as error:  # noqa: BLE001 - unknown harness failures are never skips or PASS.
        if active == "software":
            software = {"result": "FAIL", "error_type": type(error).__name__}
        else:
            runtime = {
                "preflight": "UNHEALTHY",
                "gate": "FAIL_PRODUCT",
                "result": "NOT_QUALIFIED",
                "error_type": type(error).__name__,
            }
    finally:
        final = baseline()
        save(evidence / "baseline-final.json", final)
        unchanged = initial == final
        if not unchanged:
            if args.tier in {"SOFTWARE", "FULL"}:
                software.update(
                    result="FAIL",
                    integrity_failure="SOURCE_CHANGED_DURING_VERIFICATION",
                )
            if args.tier in {"LOCAL_RUNTIME", "FULL"}:
                runtime.update(
                    gate="FAIL_PRODUCT",
                    result="NOT_QUALIFIED",
                    integrity_failure="SOURCE_CHANGED_DURING_VERIFICATION",
                )
        report = {
            "run_id": run_id,
            "retries": 0,
            "baseline": {
                key: value for key, value in initial.items() if key != "files"
            },
            "baseline_unchanged": unchanged,
            "software_verification": software,
            "local_runtime_qualification": runtime,
            "overall": overall(software, runtime),
        }
        save(evidence / "release.json", report)
        (evidence / "release.md").write_text(render(report), encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)
    # Distinct process results, never an ambiguous software/runtime aggregate Boolean.
    return (
        1
        if software["result"] == "FAIL"
        else 2
        if runtime.get("gate") == "FAIL_PRODUCT"
        else 3
        if runtime["result"] == "NOT_QUALIFIED"
        else 4
        if runtime["result"] == "SKIPPED_EXTERNAL_RUNTIME_UNHEALTHY"
        else 5
        if runtime["result"] == "LOCAL_RUNTIME_BUSY"
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
