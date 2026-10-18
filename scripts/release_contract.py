"""Fail-closed release reporting rules, independent of process/network orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from math import isfinite

SOFTWARE_GATES = frozenset(
    {
        "clean_build",
        "backend",
        "integration",
        "kdep",
        "fast",
        "frontend",
        "safe_browser",
        "legacy_browser",
        "deterministic_agent_e2e",
        "reference_contracts",
        "historical_findings",
    }
)
RUNTIME_SKIP = "SKIPPED_EXTERNAL_RUNTIME_UNHEALTHY"
SKIP_REASON = "EXTERNAL_LOCAL_PROVIDER_UNHEALTHY"


@dataclass(frozen=True)
class WarmMeasurement:
    seconds: float
    native_tokens_per_second: float | None
    reached_local_provider: bool
    http_status: int | None
    warm: bool = True
    sdk_error_type: str | None = None
    ollama_duration_seconds: float | None = None
    unique_interval_match: bool = False
    cancellation_observed: bool = False

    @property
    def valid(self) -> bool:
        if self.sdk_error_type is not None:
            return (
                self.warm
                and self.reached_local_provider
                and self.sdk_error_type == "APITimeoutError"
                and self.http_status == 500
                and 43 <= self.seconds <= 47
                and self.ollama_duration_seconds is not None
                and abs(self.ollama_duration_seconds - self.seconds) <= 2
                and self.unique_interval_match
                and self.cancellation_observed
            )
        return (
            self.warm
            and self.reached_local_provider
            and self.http_status == 200
            and isfinite(self.seconds)
            and self.seconds > 0
            and self.native_tokens_per_second is not None
            and isfinite(self.native_tokens_per_second)
            and self.native_tokens_per_second > 0
        )

    @property
    def healthy(self) -> bool:
        return (
            self.valid
            and self.sdk_error_type is None
            and self.seconds < 20
            and self.native_tokens_per_second >= 20
        )


@dataclass(frozen=True)
class PreflightEvidence:
    application_configuration_valid: bool = False
    selected_provider: str = ""
    execution_zone: str = ""
    provider_model: str = ""
    application_ready: bool = False
    authorization_verified: bool = False
    chat_gpu: bool = False
    embedding_cpu: bool = False
    expected_models_only: bool = False
    application_errors: tuple[str, ...] = ()
    security_errors: tuple[str, ...] = ()
    measurements: tuple[WarmMeasurement, ...] = ()

    @property
    def trusted_boundary(self) -> bool:
        return (
            self.application_configuration_valid
            and self.selected_provider == "ollama"
            and self.execution_zone == "LOCAL"
            and self.provider_model == "qwen3.5:9b"
            and self.application_ready
            and self.authorization_verified
            and self.chat_gpu
            and self.embedding_cpu
            and self.expected_models_only
            and not self.application_errors
            and not self.security_errors
        )

    def decision(self) -> dict:
        if (
            not self.trusted_boundary
            or len(self.measurements) != 2
            or not all(m.valid for m in self.measurements)
        ):
            return {
                "preflight": "UNHEALTHY",
                "gate": "FAIL_PRODUCT",
                "result": "NOT_QUALIFIED",
                "reason_code": "INVALID_PREFLIGHT_EVIDENCE",
            }
        if not all(m.healthy for m in self.measurements):
            return {
                "preflight": "UNHEALTHY",
                "gate": RUNTIME_SKIP,
                "result": RUNTIME_SKIP,
                "reason_code": SKIP_REASON,
            }
        return {
            "preflight": "HEALTHY",
            "gate": "READY",
            "result": "NOT_TESTED",
            "reason_code": None,
        }


@dataclass(frozen=True)
class ProviderFailureEvidence:
    """A generic timeout string or coincident HTTP 500 is insufficient."""

    sdk_error_type: str = ""
    provider: str = ""
    execution_zone: str = ""
    model: str = ""
    run_id: str = ""
    trace_id: str = ""
    provider_span_id: str = ""
    sdk_duration: float = 0
    ollama_duration: float = 0
    ollama_http_status: int | None = None
    unique_interval_match: bool = False
    cancellation_observed: bool = False
    application_error_preceded: bool = True

    @property
    def proven(self) -> bool:
        return (
            self.sdk_error_type == "APITimeoutError"
            and self.provider == "ollama"
            and self.execution_zone == "LOCAL"
            and self.model == "qwen3.5:9b"
            and bool(self.run_id and self.trace_id and self.provider_span_id)
            and 43 <= self.sdk_duration <= 47
            and abs(self.ollama_duration - self.sdk_duration) <= 2
            and self.ollama_http_status == 500
            and self.unique_interval_match
            and self.cancellation_observed
            and not self.application_error_preceded
        )


@dataclass(frozen=True)
class RuntimeTest:
    id: str
    passed: bool
    contract_failures: tuple[str, ...] = ()
    security_failures: tuple[str, ...] = ()
    harness_error: str | None = None
    provider_failure: ProviderFailureEvidence | None = None
    required_total: int = 0
    required_passed: int = 0

    def classification(self) -> str:
        # Independent correctness/security failures always take precedence.
        if self.security_failures or self.contract_failures or self.harness_error:
            return "FAIL_PRODUCT"
        if (
            self.passed
            and self.required_total > 0
            and self.required_passed == self.required_total
        ):
            return "PASS"
        if not self.passed and self.provider_failure and self.provider_failure.proven:
            return "BLOCKED_BY_LOCAL_PROVIDER"
        return "FAIL_PRODUCT"


def software_result(gates: dict[str, dict]) -> str:
    if set(gates) != SOFTWARE_GATES:
        return "FAIL"
    return (
        "PASS"
        if all(
            g["status"] == "PASS" and not g.get("unexplained_skips", 0)
            for g in gates.values()
        )
        else "FAIL"
    )


def qualify_once(
    preflight: PreflightEvidence,
    tests: tuple[tuple[str, Callable[[], RuntimeTest]], ...],
) -> dict:
    """One execution per registered test; never resume or retry a failed result."""
    decision = preflight.decision()
    report = {
        **decision,
        "provider_evidence": asdict(preflight),
        "tests": [],
        "retries": 0,
    }
    if decision["gate"] != "READY":
        return report
    if len({identifier for identifier, _ in tests}) != len(tests):
        return {
            **report,
            "gate": "FAIL_PRODUCT",
            "result": "NOT_QUALIFIED",
            "reason_code": "DUPLICATE_RUNTIME_TEST",
        }
    for identifier, execute in tests:
        try:
            result = execute()
            if result.id != identifier:
                raise ValueError("Runtime evidence identity mismatch")
        except Exception as error:  # noqa: BLE001 - generic exceptions fail; never retry or skip.
            result = RuntimeTest(identifier, False, harness_error=type(error).__name__)
        report["tests"].append(
            {**asdict(result), "classification": result.classification()}
        )
    categories = [r["classification"] for r in report["tests"]]
    if not categories or "FAIL_PRODUCT" in categories:
        report.update(gate="FAIL_PRODUCT", result="NOT_QUALIFIED")
    elif "BLOCKED_BY_LOCAL_PROVIDER" in categories:
        report.update(gate="NOT_QUALIFIED", result="NOT_QUALIFIED")
    else:
        report.update(gate="PASS", result="QUALIFIED")
    return report


def overall(software: dict, runtime: dict) -> dict:
    return {
        "software_correctness_verified": "YES"
        if software.get("result") == "PASS"
        else "NO",
        "local_model_runtime_qualified": "YES"
        if runtime.get("result") == "QUALIFIED"
        else "NOT_TESTED"
        if runtime.get("result") in {RUNTIME_SKIP, "NOT_TESTED", "LOCAL_RUNTIME_BUSY"}
        else "NO",
    }
