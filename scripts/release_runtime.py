"""One-shot real browser qualification with evidence-based provider attribution."""

import json
import os
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

import httpx

from scripts.local_provider_evidence import (
    collect_owned_traces,
    owned_run_ids,
    retain_native,
)
from scripts.local_runtime_lock import (
    LocalRuntimeBusy,
    runtime_reservation,
    runtime_worker,
)
from scripts.local_runtime_preflight import run_preflight
from scripts.release_contract import ProviderFailureEvidence, RuntimeTest, qualify_once
from scripts.release_support import ROOT


def release_plan():
    result = subprocess.run(
        ["node", "scripts/release-plan.mjs"],
        check=False,
        cwd=ROOT / "frontend",
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode:
        raise RuntimeError("Current release assertion registry could not be loaded")
    return json.loads(result.stdout)


def evaluate_artifact(identifier, body, proofs, required_total):
    security, contracts = [], []
    required = [a for a in body.get("assertions", []) if a["requirement"] == "REQUIRED"]
    if len(required) != required_total:
        contracts.append("Incomplete current required assertion plan")
    if body.get("result_category") == "SECURITY_DEFECT":
        security.append("Security assertion failed")
    failures = {a["assertion_id"]: a for a in body.get("step_failures", [])}
    provider_blocked = False
    provider_proof = None
    dependencies = set()
    for assertion in required:
        if assertion["status"] == "PASS" and assertion.get("executed"):
            if assertion["claim"] in {"typed", "reference", "new-chat", "switch-user"}:
                provider_blocked = False
            continue
        failure = failures.get(assertion["id"], {})
        terminal = failure.get("terminal") or {}
        if failure.get("result_category") == "SECURITY_DEFECT":
            security.append(assertion["id"])
        candidate = proofs.get(terminal.get("run_id"))
        if (
            terminal.get("error_code") == "llm_provider_unavailable"
            and failure.get("message") == "Expected successful persisted result."
            and candidate
            and candidate.proven
        ):
            expected = terminal.get("expected_tool")
            target = terminal.get("expected_target")
            calls = terminal.get("tool_calls", [])
            if expected and calls and not any(c.get("tool") == expected for c in calls):
                contracts.append("Wrong executed tool before provider failure")
            if (
                target
                and calls
                and not any(target in c.get("arguments", {}).values() for c in calls)
            ):
                contracts.append("Wrong target before provider failure")
            provider_proof, provider_blocked = candidate, True
        elif (
            provider_blocked
            and assertion["claim"] == "reference"
            and any(
                row.get("assertion_id") == assertion["id"]
                and row.get("error_code") == "REFERENCE_MISSING"
                and row.get("blocked_by_run_id") == provider_proof.run_id
                for row in body.get("steps", [])
            )
        ):
            dependencies.add(assertion["id"])
        elif (
            provider_blocked
            and not assertion.get("executed")
            and assertion["status"] == "BLOCKED"
            and assertion["claim"]
            in {"document", "reference", "reload", "pdf", "switch-user"}
        ):
            # A missing prerequisite is retained BLOCKED, never changed to PASS.
            continue
        else:
            contracts.append(assertion["id"])
    if any(
        row.get("test_result") == "FAIL"
        for row in body.get("steps", [])
        if row.get("requirement") != "OPTIONAL"
        and row.get("assertion_id") not in dependencies
    ):
        contracts.append("Independent evaluated product postcondition failed")
    for row in body.get("inventory_smoke", []):
        if row.get("result") == "PASS":
            continue
        candidate = proofs.get(row.get("run_id"))
        if row.get("result_category") == "SECURITY_DEFECT":
            security.append("Inventory security assertion failed")
        elif (
            row.get("failure_stage") == "provider_result"
            and row.get("run_status") != "success"
            and row.get("error_code") == "llm_provider_unavailable"
            and candidate
            and candidate.proven
        ):
            # Preserve the failed raw smoke and its unexecuted inventory checks.
            # Only its positively correlated initiating provider failure blocks.
            provider_proof = candidate
        else:
            contracts.append("Required inventory smoke failed")
    return RuntimeTest(
        identifier,
        body.get("status") == "PASS",
        tuple(contracts),
        tuple(security),
        "Runner lifecycle failed" if body.get("runner_error") else None,
        provider_proof,
        required_total,
        sum(a["status"] == "PASS" and a.get("executed", False) for a in required),
    )


def correlate_calls(traces, native):
    proofs, calls = {}, []
    for trace in traces:
        for span in trace["spans"]:
            if span["name"] != "llm.call":
                continue
            attributes = span["attributes"]
            seconds = span["end"] - span["start"]
            matches = [
                h
                for h in native["http"]
                if h["seconds"] is not None
                and abs(h["end"] - span["end"]) <= 2
                and abs(h["end"] - h["seconds"] - span["start"]) <= 2
            ]
            matched = matches[0] if len(matches) == 1 else {}
            cancellations = [
                t
                for t in native["tasks"]
                if t.get("stopped")
                and span["start"] - 0.3 <= t["start"] <= span["end"]
                and abs(t["end"] - span["end"]) <= 2
            ]
            preceded = any(
                s.get("status_code") == 2 and s["end"] <= span["start"]
                for s in trace["spans"]
                if s["name"] != "llm.call"
            )
            proof = ProviderFailureEvidence(
                attributes.get("provider.error_type", ""),
                attributes.get("model.provider", ""),
                attributes.get("execution.zone", ""),
                attributes.get("model.name", ""),
                attributes.get("run.id", ""),
                trace["trace_id"],
                span["span_id"],
                seconds,
                matched.get("seconds", 0),
                matched.get("status"),
                len(matches) == 1,
                len(cancellations) == 1,
                preceded,
            )
            if proof.proven:
                proofs[proof.run_id] = proof
            calls.append(
                {
                    **span,
                    "duration": seconds,
                    "trace_id": trace["trace_id"],
                    "provider_failure_proven": proof.proven,
                }
            )
    return proofs, calls


def execute_journey(plan, run_id, evidence, *, env=None):
    identifier = plan["id"]
    start = time.time()
    with (evidence / f"{identifier}-browser.log").open("x", encoding="utf-8") as log:
        child = subprocess.run(
            [
                "node",
                "scripts/run-e2e-journey.mjs",
                "--journey",
                identifier,
                "--run-id",
                run_id,
            ],
            check=False,
            cwd=ROOT / "frontend",
            stdout=log,
            stderr=subprocess.STDOUT,
            env={
                **(env or os.environ),
                "E2E_EXECUTION_MODE": "LOCAL_PROVIDER_DEPENDENT",
            },
        )
    end = time.time()
    artifact = (
        ROOT / "evals/results/browser-e2e" / run_id / f"journey-{identifier}.json"
    )
    body = json.loads(artifact.read_text(encoding="utf-8"))
    owned = owned_run_ids(body)
    first, traces, deadline = True, [], time.monotonic() + 90
    with httpx.Client(trust_env=False, timeout=20) as client:
        while True:
            traces = collect_owned_traces(client, owned, start, end)
            visible = {
                s["attributes"].get("run.id")
                for t in traces
                for s in t["spans"]
                if s["name"] == "agent.run"
            }
            if first:
                (evidence / f"{identifier}-trace-first.json").write_text(
                    json.dumps(
                        {"owned": sorted(owned), "visible": sorted(visible)}, indent=2
                    ),
                    encoding="utf-8",
                )
                first = False
            if owned <= visible or time.monotonic() >= deadline:
                break
            time.sleep(1)
    native = retain_native(evidence, identifier, start, end)
    proofs, calls = correlate_calls(traces, native)
    (evidence / f"{identifier}-provider-evidence.json").write_text(
        json.dumps(
            {
                "child_exit": child.returncode,
                "artifact": str(artifact),
                "raw_status": body.get("status"),
                "raw_result_category": body.get("result_category"),
                "raw_assertion_summary": body.get("assertion_summary"),
                "owned_run_ids": sorted(owned),
                "traces": traces,
                "provider_calls": calls,
                "correlated_failures": {k: asdict(v) for k, v in proofs.items()},
                "native": native,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    required_total = sum(a["requirement"] == "REQUIRED" for a in plan["assertions"])
    result = evaluate_artifact(identifier, body, proofs, required_total)
    if child.returncode != 0 and body.get("status") == "PASS":
        return RuntimeTest(
            identifier,
            False,
            harness_error="Browser lifecycle failed after writing its artifact",
            required_total=required_total,
            required_passed=result.required_passed,
        )
    if any(
        c["attributes"].get("model.provider") != "ollama"
        or c["attributes"].get("execution.zone") != "LOCAL"
        or c["attributes"].get("model.name") != "qwen3.5:9b"
        for c in calls
    ):
        return RuntimeTest(
            identifier,
            False,
            security_failures=("Unexpected provider/model/zone",),
            required_total=required_total,
            required_passed=result.required_passed,
        )
    if owned - visible:
        return RuntimeTest(
            identifier,
            False,
            harness_error="Execution trace coverage incomplete",
            required_total=required_total,
            required_passed=result.required_passed,
        )
    return result


def runtime_qualification(evidence: Path, run_id: str):
    evidence.mkdir()
    try:
        with runtime_reservation() as env:
            return _reserved_qualification(evidence, run_id, env)
    except LocalRuntimeBusy as error:
        report = {
            "preflight": "NOT_TESTED",
            "gate": "LOCAL_RUNTIME_BUSY",
            "result": "LOCAL_RUNTIME_BUSY",
            "reason_code": "LOCAL_RUNTIME_BUSY",
            "explanation": str(error),
            "tests": [],
            "retries": 0,
            "provider_calls": 0,
            "provider_timeouts": 0,
            "ollama_http_500": 0,
        }
        (evidence / "qualification.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        return report


def _reserved_qualification(evidence, run_id, env):
    with runtime_worker(env):
        preflight = run_preflight(evidence)
    plan = release_plan()
    report = qualify_once(
        preflight,
        tuple(
            (
                item["id"],
                lambda item=item: execute_journey(item, run_id, evidence, env=env),
            )
            for item in plan
        ),
    )
    calls = []
    raw = []
    for path in evidence.glob("*-provider-evidence.json"):
        item = json.loads(path.read_text(encoding="utf-8"))
        calls.extend(item["provider_calls"])
        raw.append(
            {
                key: item[key]
                for key in (
                    "artifact",
                    "raw_status",
                    "raw_result_category",
                    "raw_assertion_summary",
                )
            }
        )
    preflight_calls = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in [
            evidence / "warmup.json",
            evidence / "measured-1.json",
            evidence / "measured-2.json",
        ]
        if p.exists()
    ]
    report.update(
        provider="Ollama",
        model="qwen3.5:9b",
        raw_artifacts=raw,
        provider_calls=len(calls) + len(preflight_calls),
        qualification_provider_calls=len(calls),
        preflight_provider_calls=len(preflight_calls),
        provider_timeouts=sum(
            c["attributes"].get("provider.error_type") == "APITimeoutError"
            for c in calls
        )
        + sum(c.get("sdk_error_type") == "APITimeoutError" for c in preflight_calls),
        maximum_provider_duration=max(
            [c["duration"] for c in calls] + [c["seconds"] for c in preflight_calls],
            default=None,
        ),
        ollama_http_500=sum(
            h["status"] == 500
            for path in evidence.glob("*-provider-evidence.json")
            for h in json.loads(path.read_text(encoding="utf-8"))["native"]["http"]
        )
        + sum(h["status"] == 500 for c in preflight_calls for h in c["native"]["http"]),
    )
    (evidence / "qualification.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return report
