import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts.local_runtime_lock import (
    LocalRuntimeBusy,
    runtime_reservation,
    runtime_worker,
)
from scripts.release_contract import overall

ROOT = Path(__file__).resolve().parents[2]


def lease_port(env):
    return json.loads(env["LOCAL_RUNTIME_LEASE"])["port"]


@pytest.mark.parametrize("exit_type", [None, RuntimeError, KeyboardInterrupt])
def test_reservation_releases_after_success_exception_or_cancellation(exit_type):
    port = None
    try:
        with runtime_reservation(port=0) as env:
            port = lease_port(env)
            with pytest.raises(LocalRuntimeBusy), runtime_reservation(port=port):
                pytest.fail("second controller must not enter")
            if exit_type:
                raise exit_type()
    except (RuntimeError, KeyboardInterrupt):
        if exit_type is None:
            raise
    with runtime_reservation(port=port):
        pass


def test_python_and_node_share_the_same_single_worker_slot():
    with runtime_reservation(port=0) as env:
        port = lease_port(env)
        code = f"""import {{withRuntimeWorker}} from './frontend/scripts/local-runtime-lock.mjs';
try {{ await withRuntimeWorker(()=>process.exit(99), {{port:{port}}}); }}
catch(error) {{console.log(error.code);}}"""
        with runtime_worker(env):
            result = subprocess.run(
                ["node", "--input-type=module", "-e", code],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            assert result.stdout.strip() == "LOCAL_RUNTIME_BUSY"


def test_busy_runtime_returns_before_preflight_and_does_not_fail_software(
    monkeypatch, tmp_path
):
    import scripts.release_runtime as runtime

    with runtime_reservation(port=0) as env:
        monkeypatch.setattr(
            runtime,
            "runtime_reservation",
            lambda: runtime_reservation(port=lease_port(env)),
        )
        monkeypatch.setattr(
            runtime,
            "run_preflight",
            lambda *a: pytest.fail("provider preflight must not run"),
        )
        result = runtime.runtime_qualification(tmp_path / "busy", "test-busy")
    assert result["result"] == "LOCAL_RUNTIME_BUSY"
    assert result["preflight"] == "NOT_TESTED"
    assert result["provider_calls"] == 0
    assert overall({"result": "PASS"}, result) == {
        "software_correctness_verified": "YES",
        "local_model_runtime_qualified": "NOT_TESTED",
    }


@pytest.mark.parametrize("outcome", ["PASS", "FAIL", RuntimeError, KeyboardInterrupt])
def test_actual_runtime_controller_holds_reservation_through_completion_and_releases(
    monkeypatch, tmp_path, outcome
):
    import scripts.release_runtime as runtime

    leases = []

    def reserve():
        reservation = runtime_reservation(port=0)
        return reservation

    original_worker = runtime.runtime_worker

    def worker(env):
        leases.append(env)
        return original_worker(env)

    def assert_reserved():
        with (
            pytest.raises(LocalRuntimeBusy),
            runtime_reservation(port=lease_port(leases[0])),
        ):
            pytest.fail("GPU must stay reserved")

    def preflight(_):
        assert_reserved()
        return object()

    def qualify(*_):
        assert_reserved()
        if isinstance(outcome, type):
            raise outcome()
        return {
            "preflight": "HEALTHY",
            "gate": outcome,
            "result": "QUALIFIED" if outcome == "PASS" else "NOT_QUALIFIED",
        }

    monkeypatch.setattr(runtime, "runtime_reservation", reserve)
    monkeypatch.setattr(runtime, "runtime_worker", worker)
    monkeypatch.setattr(runtime, "run_preflight", preflight)
    monkeypatch.setattr(runtime, "release_plan", list)
    monkeypatch.setattr(runtime, "qualify_once", qualify)
    if isinstance(outcome, type):
        with pytest.raises(outcome):
            runtime.runtime_qualification(tmp_path / "qualification", "test-owner")
    else:
        result = runtime.runtime_qualification(tmp_path / "qualification", "test-owner")
        assert result["gate"] == outcome
    with runtime_reservation(port=lease_port(leases[0])):
        pass


@pytest.mark.parametrize("tier", ["SOFTWARE", "FULL"])
def test_gate_order_and_software_never_acquires_runtime_lock(
    monkeypatch, tmp_path, tier
):
    import scripts.run_release_gate as runner

    events = []
    baseline = {"branch": "test", "head": "test", "files": {}, "fingerprint": "test"}
    monkeypatch.setattr(runner, "baseline", lambda: baseline)
    monkeypatch.setattr(sys, "argv", ["gate", tier, "--output", str(tmp_path / tier)])

    def software(*args):
        events.append("software-finished")
        return {"result": "PASS", "gates": {}}

    def runtime(*args):
        assert events == ["software-finished"]
        events.append("runtime-started")
        return {"result": "LOCAL_RUNTIME_BUSY", "gate": "LOCAL_RUNTIME_BUSY"}

    monkeypatch.setattr(runner, "software_verification", software)
    monkeypatch.setattr(runner, "runtime_qualification", runtime)
    assert runner.main() == (0 if tier == "SOFTWARE" else 5)
    assert events == (
        ["software-finished"]
        if tier == "SOFTWARE"
        else ["software-finished", "runtime-started"]
    )


@pytest.mark.parametrize(
    "script", ["run-e2e-journey.mjs", "run-manual-e2e.mjs", "playwright"]
)
def test_manual_real_entry_points_are_busy_before_any_api_or_chat_call(script):
    with runtime_reservation(port=0) as env:
        command = (
            [
                "node",
                "frontend/node_modules/@playwright/test/cli.js",
                "test",
                "-c",
                "frontend/playwright.config.mjs",
            ]
            if script == "playwright"
            else [
                "node",
                f"frontend/scripts/{script}",
                "--journey",
                "s04-investigation",
                "--run-id",
                "must-not-execute",
            ]
        )
        result = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={
                **os.environ,
                "E2E_API_URL": "http://127.0.0.1:9",
                "E2E_FRONTEND_URL": "http://127.0.0.1:9",
                "AGENT_API_MODEL_ADMIN_TOKEN": "fixture-admin-token",
                "NODE_OPTIONS": "--import="
                + (
                    ROOT / "tests/frontend/fixtures/runtime-port-isolation.mjs"
                ).as_uri(),
                "TEST_RUNTIME_PORT": str(lease_port(env)),
            },
            check=False,
        )
        assert result.returncode == (1 if script == "playwright" else 5)
        assert "LOCAL_RUNTIME_BUSY" in result.stderr + result.stdout


def test_dead_controller_does_not_leave_a_stale_reservation():
    code = """from scripts.local_runtime_lock import runtime_reservation
import json,sys
with runtime_reservation(port=0) as env:
 print(json.loads(env['LOCAL_RUNTIME_LEASE'])['port'],flush=True)
 sys.stdin.read()
"""
    owner = subprocess.Popen(
        [sys.executable, "-c", code],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        port = int(owner.stdout.readline())
        owner.terminate()
        owner.wait(timeout=5)
        deadline = time.monotonic() + 5
        while True:
            try:
                with runtime_reservation(port=port):
                    break
            except LocalRuntimeBusy:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=5)
        owner.stdin.close()
        owner.stdout.close()
