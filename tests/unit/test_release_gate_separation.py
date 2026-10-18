"""Release decisions must preserve software failures and first provider evidence."""

from dataclasses import replace

import pytest

from scripts.release_contract import (
    RUNTIME_SKIP,
    SKIP_REASON,
    SOFTWARE_GATES,
    PreflightEvidence,
    ProviderFailureEvidence,
    RuntimeTest,
    WarmMeasurement,
    overall,
    qualify_once,
    software_result,
)


def healthy():
    return PreflightEvidence(
        application_configuration_valid=True,
        selected_provider="ollama",
        execution_zone="LOCAL",
        provider_model="qwen3.5:9b",
        application_ready=True,
        authorization_verified=True,
        chat_gpu=True,
        embedding_cpu=True,
        expected_models_only=True,
        measurements=(
            WarmMeasurement(5, 32, True, 200),
            WarmMeasurement(6, 31, True, 200),
        ),
    )


def timeout():
    return ProviderFailureEvidence(
        sdk_error_type="APITimeoutError",
        provider="ollama",
        execution_zone="LOCAL",
        model="qwen3.5:9b",
        run_id="owned-run",
        trace_id="execution-trace",
        provider_span_id="owned-provider-span",
        sdk_duration=45.05,
        ollama_duration=45.02,
        ollama_http_status=500,
        unique_interval_match=True,
        cancellation_observed=True,
        application_error_preceded=False,
    )


def test_software_failure_is_independent_of_runtime_qualification():
    gates = {name: {"status": "PASS"} for name in SOFTWARE_GATES}
    gates["backend"] = {"status": "FAIL"}
    assert software_result(gates) == "FAIL"
    assert overall({"result": "FAIL"}, {"result": "QUALIFIED"}) == {
        "software_correctness_verified": "NO",
        "local_model_runtime_qualified": "YES",
    }


def test_healthy_runtime_and_complete_product_contracts_qualify():
    result = qualify_once(
        healthy(),
        (
            (
                "journey",
                lambda: RuntimeTest(
                    "journey", True, required_total=5, required_passed=5
                ),
            ),
        ),
    )
    assert result["gate"] == "PASS"
    assert result["result"] == "QUALIFIED"


def test_provider_unhealthy_preflight_skips_without_invoking_journeys():
    proof = replace(
        healthy(),
        measurements=(
            WarmMeasurement(19, 8, True, 200),
            WarmMeasurement(32, 7, True, 200),
        ),
    )

    def forbidden():
        pytest.fail("An unhealthy provider must not trigger dozens of journeys")

    result = qualify_once(proof, (("journey", forbidden),))
    assert result["result"] == RUNTIME_SKIP
    assert result["reason_code"] == SKIP_REASON
    assert result["tests"] == []
    assert overall({"result": "PASS"}, result) == {
        "software_correctness_verified": "YES",
        "local_model_runtime_qualified": "NOT_TESTED",
    }


def test_provider_timeout_after_healthy_preflight_blocks_qualification_only():
    result = qualify_once(
        healthy(),
        (
            (
                "journey",
                lambda: RuntimeTest(
                    "journey",
                    False,
                    provider_failure=timeout(),
                    required_total=5,
                    required_passed=2,
                ),
            ),
        ),
    )
    assert result["tests"][0]["classification"] == "BLOCKED_BY_LOCAL_PROVIDER"
    assert result["result"] == "NOT_QUALIFIED"
    gates = {name: {"status": "PASS"} for name in SOFTWARE_GATES}
    assert software_result(gates) == "PASS"
    assert overall({"result": "PASS"}, result)["software_correctness_verified"] == "YES"


@pytest.mark.parametrize(
    "defect",
    [
        "wrong tool",
        "wrong target",
        "missing tool",
        "wrong clearance",
        "wrong persistence",
        "wrong reference",
        "response contract",
        "RLS failure",
        "lifecycle cleanup",
    ],
)
def test_product_contract_violation_cannot_be_excused_by_simultaneous_timeout(defect):
    result = RuntimeTest(
        "journey", False, contract_failures=(defect,), provider_failure=timeout()
    )
    assert result.classification() == "FAIL_PRODUCT"


def test_security_violation_cannot_be_reclassified_as_provider_failure():
    assert (
        RuntimeTest(
            "leak",
            False,
            security_failures=("hidden data leak",),
            provider_failure=timeout(),
        ).classification()
        == "FAIL_PRODUCT"
    )
    invalid = replace(
        healthy(),
        security_errors=("unauthorized run",),
        measurements=(WarmMeasurement(40, 5, True, 200),) * 2,
    )
    assert invalid.decision()["gate"] == "FAIL_PRODUCT"
    assert invalid.decision()["reason_code"] != SKIP_REASON


@pytest.mark.parametrize(
    "mutation",
    [
        {"application_configuration_valid": False},
        {"authorization_verified": False},
        {"selected_provider": "cloud"},
        {"execution_zone": "PUBLIC_CLOUD"},
        {"application_errors": ("RuntimeError",)},
        {"embedding_cpu": False},
        {"measurements": ()},
        {"measurements": (WarmMeasurement(45, None, False, None),) * 2},
        {"measurements": (WarmMeasurement(40, 5, True, 200, warm=False),) * 2},
    ],
)
def test_incomplete_or_invalid_preflight_is_never_a_provider_skip(mutation):
    result = replace(healthy(), **mutation).decision()
    assert result["gate"] == "FAIL_PRODUCT"
    assert result["reason_code"] != SKIP_REASON


def test_generic_runtime_exception_is_not_a_provider_skip_and_later_tests_execute_once():
    called = []

    def broken():
        called.append("broken")
        raise TimeoutError("a generic browser timeout is not SDK evidence")

    def following():
        called.append("following")
        return RuntimeTest("following", True, required_total=1, required_passed=1)

    result = qualify_once(healthy(), (("broken", broken), ("following", following)))
    assert result["gate"] == "FAIL_PRODUCT"
    assert called == ["broken", "following"]
    assert result["retries"] == 0


@pytest.mark.parametrize(
    "mutation",
    [
        {"sdk_error_type": "TimeoutError"},
        {"unique_interval_match": False},
        {"ollama_http_status": 200},
        {"cancellation_observed": False},
        {"application_error_preceded": True},
        {"trace_id": ""},
        {"ollama_duration": 2},
        {"provider": "external"},
    ],
)
def test_provider_block_requires_exact_local_execution_correlation(mutation):
    assert (
        RuntimeTest(
            "journey", False, provider_failure=replace(timeout(), **mutation)
        ).classification()
        == "FAIL_PRODUCT"
    )


def test_first_failed_runtime_result_is_retained_without_retry_to_pass():
    calls = 0

    def unstable():
        nonlocal calls
        calls += 1
        return RuntimeTest(
            "first",
            calls > 1,
            provider_failure=timeout(),
            required_total=1,
            required_passed=int(calls > 1),
        )

    result = qualify_once(healthy(), (("first", unstable),))
    assert calls == 1
    assert result["result"] == "NOT_QUALIFIED"
    assert result["tests"][0]["classification"] == "BLOCKED_BY_LOCAL_PROVIDER"


def test_incomplete_assertion_plan_and_missing_software_gate_cannot_pass():
    assert (
        RuntimeTest(
            "partial", True, required_total=5, required_passed=4
        ).classification()
        == "FAIL_PRODUCT"
    )
    assert software_result({"backend": {"status": "PASS"}}) == "FAIL"
    gates = {name: {"status": "PASS"} for name in SOFTWARE_GATES}
    gates["integration"]["unexplained_skips"] = 1
    assert software_result(gates) == "FAIL"


def test_correlated_sdk_timeout_during_preflight_can_skip_but_generic_timeout_cannot():
    timed_out = WarmMeasurement(
        45.03, None, True, 500, True, "APITimeoutError", 45.01, True, True
    )
    proof = replace(healthy(), measurements=(timed_out, timed_out))
    assert proof.decision()["reason_code"] == SKIP_REASON
    assert (
        replace(
            proof,
            measurements=(replace(timed_out, sdk_error_type="TimeoutError"), timed_out),
        ).decision()["gate"]
        == "FAIL_PRODUCT"
    )


def test_duplicate_registry_ids_are_rejected_before_any_execution():
    called = []

    def execute():
        called.append(True)
        return RuntimeTest("same", True, required_total=1, required_passed=1)

    result = qualify_once(healthy(), (("same", execute), ("same", execute)))
    assert result["reason_code"] == "DUPLICATE_RUNTIME_TEST"
    assert called == []


def test_frozen_preflight_preserves_real_provider_request_shape_without_deadline_override():
    from scripts.local_runtime_preflight import frozen_request

    request = frozen_request()
    assert len(request.messages) == 4
    assert len(request.tools) == 2
    assert request.max_output_tokens == 192
    assert request.reasoning_effort.value == "none"
    assert request.timeout_seconds is None


def test_artifact_consumer_keeps_independent_security_and_contract_failures():
    from scripts.release_runtime import evaluate_artifact

    body = {
        "status": "FAIL",
        "assertions": [
            {
                "id": "step-1:typed",
                "claim": "typed",
                "requirement": "REQUIRED",
                "status": "FAIL",
                "executed": True,
            },
            {
                "id": "step-2:pdf",
                "claim": "pdf",
                "requirement": "REQUIRED",
                "status": "FAIL",
                "executed": True,
            },
        ],
        "step_failures": [
            {
                "assertion_id": "step-1:typed",
                "message": "Expected successful persisted result.",
                "terminal": {
                    "run_id": "owned-run",
                    "error_code": "llm_provider_unavailable",
                },
            },
            {
                "assertion_id": "step-2:pdf",
                "result_category": "SECURITY_DEFECT",
                "message": "Protected document leaked",
            },
        ],
    }
    result = evaluate_artifact("journey", body, {"owned-run": timeout()}, 2)
    assert result.classification() == "FAIL_PRODUCT"
    assert result.security_failures
    body["step_failures"][1]["result_category"] = "PRODUCT_DEFECT"
    result = evaluate_artifact("journey", body, {"owned-run": timeout()}, 2)
    assert result.contract_failures
    assert result.classification() == "FAIL_PRODUCT"


def test_artifact_consumer_blocks_only_correlated_provider_and_unexecuted_dependencies():
    from scripts.release_runtime import evaluate_artifact

    body = {
        "status": "FAIL",
        "assertions": [
            {
                "id": "step-1:typed",
                "claim": "typed",
                "requirement": "REQUIRED",
                "status": "FAIL",
                "executed": True,
            },
            {
                "id": "step-2:pdf",
                "claim": "pdf",
                "requirement": "REQUIRED",
                "status": "BLOCKED",
                "executed": False,
            },
        ],
        "step_failures": [
            {
                "assertion_id": "step-1:typed",
                "message": "Expected successful persisted result.",
                "terminal": {
                    "run_id": "owned-run",
                    "error_code": "llm_provider_unavailable",
                },
            }
        ],
    }
    assert (
        evaluate_artifact("journey", body, {"owned-run": timeout()}, 2).classification()
        == "BLOCKED_BY_LOCAL_PROVIDER"
    )
    assert evaluate_artifact("journey", body, {}, 2).classification() == "FAIL_PRODUCT"
    body["step_failures"][0]["message"] = (
        "UI investigation reference does not match the persisted run."
    )
    assert (
        evaluate_artifact("journey", body, {"owned-run": timeout()}, 2).classification()
        == "FAIL_PRODUCT"
    )


def test_actual_junit_skip_ledger_rejects_unknown_software_skip(tmp_path):
    from scripts.run_release_gate import junit_result

    xml = tmp_path / "tests.xml"
    xml.write_text(
        '<testsuite><testcase classname="software" name="security"><skipped message="unhealthy provider"/></testcase></testsuite>'
    )
    result = junit_result(xml, 0)
    assert result["status"] == "FAIL"
    assert result["unexplained_skips"] == 1


def test_existing_native_logs_and_trace_identity_prove_a_provider_timeout(monkeypatch):
    from types import SimpleNamespace

    from scripts.local_provider_evidence import native_window
    from scripts.release_runtime import correlate_calls

    logs = (
        "1970-01-01T00:00:01.010Z slot launch_slot_: id 0 | task 162 | processing task, is_child = 0\n"
        "1970-01-01T00:00:46.010Z slot print_timing: id 0 | task 162 | eval time = 19000.00 ms / 158 tokens (120.00 ms per token, 8.26 tokens per second)\n"
        "1970-01-01T00:00:46.011Z slot release: id 0 | task 162 | stop processing: n_tokens = 1261, truncated = 0\n"
        '1970-01-01T00:00:46.020Z [GIN] 1970/01/01 | 500 | 45.020s | 127.0.0.1 | POST "/v1/chat/completions"'
    )
    monkeypatch.setattr(
        "scripts.local_provider_evidence.subprocess.run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=logs, stderr=""),
    )
    native = native_window(1, 46.05)
    assert native["tasks"][0]["native_tps"] == 8.26
    trace = {
        "trace_id": "execution-trace",
        "spans": [
            {
                "name": "llm.call",
                "span_id": "provider-span",
                "start": 1,
                "end": 46.05,
                "attributes": {
                    "run.id": "owned-run",
                    "provider.error_type": "APITimeoutError",
                    "model.provider": "ollama",
                    "execution.zone": "LOCAL",
                    "model.name": "qwen3.5:9b",
                },
            }
        ],
    }
    proofs, calls = correlate_calls([trace], native)
    assert proofs["owned-run"].proven
    assert calls[0]["provider_failure_proven"]
    native["http"].append(dict(native["http"][0]))
    assert not correlate_calls([trace], native)[0], (
        "Ambiguous backend ordering cannot establish ownership"
    )


def test_application_error_before_provider_call_disallows_external_attribution():
    from scripts.release_runtime import correlate_calls

    trace = {
        "trace_id": "execution-trace",
        "spans": [
            {
                "name": "factory.tool",
                "start": 0,
                "end": 0.5,
                "status_code": 2,
                "attributes": {},
            },
            {
                "name": "llm.call",
                "span_id": "provider-span",
                "start": 1,
                "end": 46,
                "attributes": {
                    "run.id": "owned-run",
                    "provider.error_type": "APITimeoutError",
                    "model.provider": "ollama",
                    "execution.zone": "LOCAL",
                    "model.name": "qwen3.5:9b",
                },
            },
        ],
    }
    native = {
        "http": [{"status": 500, "seconds": 45, "end": 46}],
        "tasks": [{"start": 1.1, "end": 46, "stopped": True}],
    }
    assert not correlate_calls([trace], native)[0]


@pytest.mark.parametrize(
    ("mutation", "correlated", "classification"),
    [
        ({}, True, "BLOCKED_BY_LOCAL_PROVIDER"),
        ({"failure_stage": "inventory_contract"}, True, "FAIL_PRODUCT"),
        ({"result_category": "SECURITY_DEFECT"}, True, "FAIL_PRODUCT"),
        ({}, False, "FAIL_PRODUCT"),
    ],
)
def test_inventory_smoke_retains_provider_failure_and_independent_contracts(
    mutation, correlated, classification
):
    from scripts.release_runtime import evaluate_artifact

    row = {
        "result": "FAIL",
        "run_id": "owned-run",
        "run_status": "error",
        "error_code": "llm_provider_unavailable",
        "failure_stage": "provider_result",
        **mutation,
    }
    body = {
        "status": "FAIL",
        "assertions": [
            {
                "id": "step-1:typed",
                "claim": "typed",
                "requirement": "REQUIRED",
                "status": "PASS",
                "executed": True,
            }
        ],
        "inventory_smoke": [row],
    }
    proof = {"owned-run": timeout()} if correlated else {}
    result = evaluate_artifact("discovery", body, proof, 1)
    assert result.classification() == classification
    assert body["inventory_smoke"][0]["result"] == "FAIL"


@pytest.mark.parametrize("duplicate", [False, True])
def test_preflight_measurement_correlates_chat_not_preceding_embedding(
    monkeypatch, tmp_path, duplicate
):
    from types import SimpleNamespace

    from scripts.local_runtime_preflight import measure

    clock, wall = iter((0, 5)), iter((100, 105))
    monkeypatch.setattr(
        "scripts.local_runtime_preflight.time.perf_counter", lambda: next(clock)
    )
    monkeypatch.setattr("scripts.local_runtime_preflight.time.time", lambda: next(wall))
    task = {"start": 100, "end": 105, "stopped": True, "native_tps": 35}
    native = {
        "http": [{"end": 105, "seconds": 5, "status": 200}],
        "tasks": [
            {"start": 99.9, "end": 100.01, "stopped": True},
            task,
            *([dict(task)] if duplicate else []),
        ],
    }
    monkeypatch.setattr(
        "scripts.local_runtime_preflight.retain_native", lambda *a: native
    )
    http = SimpleNamespace(
        get=lambda *a: SimpleNamespace(
            json=lambda: {"models": [{"name": "qwen3.5:9b"}]}
        )
    )
    client = SimpleNamespace(
        chat=lambda *a: SimpleNamespace(
            text="Synthetic answer", tool_calls=(), usage=None
        )
    )
    result = measure(client, "measured-1", tmp_path, http)
    assert result.healthy is (not duplicate)
    assert result.native_tokens_per_second == (None if duplicate else 35)


@pytest.mark.parametrize("anonymous_status", [200, 401, 403])
@pytest.mark.parametrize("embedding_evicted", [False, True])
def test_real_preflight_control_accepts_denial_and_checks_effective_context(
    monkeypatch, tmp_path, anonymous_status, embedding_evicted
):
    from contextlib import nullcontext
    from types import SimpleNamespace

    from scripts.local_runtime_preflight import run_preflight

    calls = []
    monkeypatch.setenv("AGENT_API_MODEL_ADMIN_TOKEN", "test-model-admin")
    loaded = [
        {"name": "qwen3.5:9b", "size": 1000, "size_vram": 1000, "context_length": 4096},
        {"name": "qwen3-embedding:0.6b", "size": 100, "size_vram": 0},
    ]

    def response(body, status=200):
        return SimpleNamespace(
            status_code=status, json=lambda: body, raise_for_status=lambda: None
        )

    ps_calls = 0

    def get(url, headers=None):
        nonlocal ps_calls
        if url.endswith("/model-assignments"):
            if headers is None:
                return response({}, anonymous_status)
            return response(
                [
                    {
                        "consumer_id": "agent",
                        "model_id": "local_quality",
                        "selection_mode": "MANUAL",
                    }
                    for _ in range(4)
                ]
            )
        if url.endswith("/models"):
            return response(
                [
                    {
                        "model_id": "local_quality",
                        "provider": "ollama",
                        "provider_model": "qwen3.5:9b",
                        "execution_zone": "LOCAL",
                    }
                ]
            )
        if url.endswith("/api/tags"):
            return response({"models": loaded})
        if url.endswith("/api/ps"):
            ps_calls += 1
            return response(
                {
                    "models": loaded[:1]
                    if embedding_evicted and ps_calls >= 3
                    else loaded
                }
            )
        return response({})

    def post(url, json):
        embedding = json["model"] == "qwen3-embedding:0.6b"
        return response(
            {
                "details": {"quantization_level": "Q4_K_M"},
                "parameters": "num_gpu 0" if embedding else "temperature 1",
            }
        )

    fake_http = SimpleNamespace(get=get, post=post)
    monkeypatch.setattr(
        "scripts.local_runtime_preflight.httpx.Client",
        lambda **k: nullcontext(fake_http),
    )
    monkeypatch.setattr(
        "scripts.local_runtime_preflight.OllamaEmbeddingClient",
        lambda: SimpleNamespace(embed_query=lambda *a, **k: [0.0] * 1024),
    )
    monkeypatch.setattr(
        "scripts.local_runtime_preflight.OpenAICompatibleLLMClient",
        lambda *a: nullcontext(None),
    )

    def measured(client, label, evidence, http):
        calls.append(label)
        return WarmMeasurement(4, 35, True, 200)

    monkeypatch.setattr("scripts.local_runtime_preflight.measure", measured)
    result = run_preflight(tmp_path)
    assert result.decision()["gate"] == (
        "FAIL_PRODUCT" if anonymous_status == 200 else "READY"
    )
    assert calls == ([] if anonymous_status == 200 else ["measured-1", "measured-2"])
