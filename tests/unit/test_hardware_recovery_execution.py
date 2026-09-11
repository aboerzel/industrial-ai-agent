"""Deterministic approval and execution regressions for Hardware MCP recovery."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from industrial_ai_agent.application.hardware_recovery import (
    HardwareRecoveryExecutionService,
    HardwareRecoveryNotAccessibleError,
    HardwareRecoveryPreparationService,
    TrustedRecoveryApprovalClaimPort,
)
from industrial_ai_agent.domain.closed_loop_recovery import (
    RecoveryOutcome,
    VerificationStatus,
)
from industrial_ai_agent.domain.machine_status import MachineState
from industrial_ai_agent.domain.physical_device import DeviceId
from industrial_ai_agent.domain.product_history import StationId
from industrial_ai_agent.domain.security import (
    DEMO_ENGINEER_SECURITY_CONTEXT,
    DataClassification,
    SecurityContext,
)
from industrial_ai_agent.infrastructure.api.run_store import InMemoryAgentRunStore
from industrial_ai_agent.infrastructure.hardware_mcp_server import (
    create_hardware_mcp_server,
)
from industrial_ai_agent.infrastructure.hardware_recovery_approval import (
    AgentRunStoreRecoveryApprovalPort,
)
from industrial_ai_agent.infrastructure.simulated_position_encoder_adapter import (
    SimulatedCalibrationOutcome,
    SimulatedPositionEncoderAdapter,
)

RUN_ID = uuid4()
ACTION_ID = "reference-calibration-call-1"
STATION_ID = StationId("S04")
DEVICE_ID = DeviceId("POSITION-ENC-02")


class RecordingPositionEncoderAdapter(SimulatedPositionEncoderAdapter):
    def __init__(
        self,
        calibration_outcome: SimulatedCalibrationOutcome = SimulatedCalibrationOutcome.SUCCESS,
    ) -> None:
        super().__init__(calibration_outcome)
        self.execute_calls = 0

    def execute_operation(self, operation):  # type: ignore[no-untyped-def]
        self.execute_calls += 1
        return super().execute_operation(operation)


@dataclass
class RecordingRecoveryTelemetry:
    lifecycle_events: list[dict[str, str]]
    span_attributes: list[dict[str, str]]

    def record_recovery_lifecycle(
        self,
        *,
        stage: str,
        outcome: str,
        verification_status: str,
        classification: str,
    ) -> None:
        self.lifecycle_events.append(
            {
                "stage": stage,
                "outcome": outcome,
                "verification_status": verification_status,
                "classification": classification,
            }
        )

    def set_current_span_attributes(self, attributes: dict[str, str]) -> None:
        self.span_attributes.append(attributes)


@dataclass
class TrustedApprovalClaims(TrustedRecoveryApprovalClaimPort):
    approved_bindings: set[tuple[UUID, str, StationId, DeviceId]]
    on_claim: Callable[[], None] | None = None

    async def claim_reference_calibration(
        self,
        *,
        run_id: UUID,
        action_id: str,
        station_id: StationId,
        device_id: DeviceId,
    ) -> bool:
        if self.on_claim is not None:
            self.on_claim()
        binding = (run_id, action_id, station_id, device_id)
        if binding not in self.approved_bindings:
            return False
        self.approved_bindings.remove(binding)
        return True


def test_approved_execution_succeeds_through_closed_loop_recovery() -> None:
    adapter = RecordingPositionEncoderAdapter()
    service = _execution_service(adapter)

    result = asyncio.run(_execute(service))

    assert result.outcome is RecoveryOutcome.SUCCEEDED
    assert result.action_executed is True
    assert result.verification.status is VerificationStatus.PASSED
    assert adapter.execute_calls == 1


def test_missing_or_rejected_approval_blocks_without_physical_execution() -> None:
    adapter = RecordingPositionEncoderAdapter()
    service = _execution_service(adapter, approved_bindings=set())

    result = asyncio.run(_execute(service))

    assert result.outcome is RecoveryOutcome.BLOCKED
    assert result.action_executed is False
    assert adapter.execute_calls == 0


def test_approval_is_bound_to_exact_action_and_consumed_after_one_use() -> None:
    adapter = RecordingPositionEncoderAdapter()
    service = _execution_service(adapter)

    wrong_action = asyncio.run(_execute(service, action_id="other-action"))
    first = asyncio.run(_execute(service))
    replay = asyncio.run(_execute(service))

    assert wrong_action.outcome is RecoveryOutcome.BLOCKED
    assert first.outcome is RecoveryOutcome.SUCCEEDED
    assert replay.outcome is RecoveryOutcome.BLOCKED
    assert adapter.execute_calls == 1


def test_state_change_after_approval_blocks_before_physical_execution() -> None:
    adapter = RecordingPositionEncoderAdapter()
    claims = TrustedApprovalClaims(
        approved_bindings={(RUN_ID, ACTION_ID, STATION_ID, DEVICE_ID)},
        on_claim=lambda: setattr(adapter, "_station_mode", MachineState.RUNNING),
    )
    service = _execution_service(adapter, approval_claims=claims)

    result = asyncio.run(_execute(service))

    assert result.outcome is RecoveryOutcome.BLOCKED
    assert result.action_executed is False
    assert adapter.execute_calls == 0


def test_unavailable_target_or_clearance_does_not_consume_a_pending_approval() -> None:
    adapter = RecordingPositionEncoderAdapter()
    service = _execution_service(adapter)
    insufficient_clearance = SecurityContext(
        subject_id="internal-reader",
        roles=("internal-reader",),
        clearance=DataClassification.INTERNAL,
        authenticated=True,
    )

    with pytest.raises(HardwareRecoveryNotAccessibleError):
        asyncio.run(
            service.execute_reference_calibration(
                run_id=RUN_ID,
                action_id=ACTION_ID,
                station_id=STATION_ID,
                device_id=DEVICE_ID,
                security_context=insufficient_clearance,
                mcp_execution_permitted=True,
            )
        )

    assert asyncio.run(_execute(service)).outcome is RecoveryOutcome.SUCCEEDED


@pytest.mark.parametrize(
    ("outcome", "expected_verification"),
    (
        (SimulatedCalibrationOutcome.VERIFICATION_FAILURE, VerificationStatus.FAILED),
        (SimulatedCalibrationOutcome.EXECUTION_FAILURE, VerificationStatus.NOT_RUN),
    ),
)
def test_execution_and_verification_failures_never_report_recovery_success(
    outcome: SimulatedCalibrationOutcome, expected_verification: VerificationStatus
) -> None:
    adapter = RecordingPositionEncoderAdapter(outcome)
    service = _execution_service(adapter)

    result = asyncio.run(_execute(service))

    assert result.outcome is RecoveryOutcome.FAILED
    assert result.verification.status is expected_verification
    assert adapter.execute_calls == 1


def test_hardware_mcp_execute_accepts_only_server_injected_execution_fields() -> None:
    adapter = RecordingPositionEncoderAdapter()
    server = create_hardware_mcp_server(
        recovery_preparation=HardwareRecoveryPreparationService(
            physical_devices=adapter
        ),
        recovery_execution=_execution_service(adapter),
    )

    result = asyncio.run(_call_execute(server, run_id=str(RUN_ID), action_id=ACTION_ID))

    assert result["recovery_outcome"] == "SUCCEEDED"
    assert result["action_executed"] is True
    assert adapter.execute_calls == 1

    async def forged_call() -> None:
        with pytest.raises(ToolError):
            await server.call_tool(
                "execute_reference_calibration",
                {
                    "station_id": "S04",
                    "device_id": "POSITION-ENC-02",
                    "run_id": str(RUN_ID),
                    "action_id": ACTION_ID,
                    "approved": True,
                },
            )

    asyncio.run(forged_call())


def test_hardware_mcp_emits_bounded_lifecycle_signals_for_execution() -> None:
    adapter = RecordingPositionEncoderAdapter()
    telemetry = RecordingRecoveryTelemetry(lifecycle_events=[], span_attributes=[])
    server = create_hardware_mcp_server(
        recovery_preparation=HardwareRecoveryPreparationService(
            physical_devices=adapter
        ),
        recovery_execution=_execution_service(adapter),
        telemetry=telemetry,  # type: ignore[arg-type]
    )

    result = asyncio.run(_call_execute(server, run_id=str(RUN_ID), action_id=ACTION_ID))

    assert result["recovery_outcome"] == "SUCCEEDED"
    assert telemetry.lifecycle_events == [
        {
            "stage": "action_attempted",
            "outcome": "PENDING",
            "verification_status": "NOT_RUN",
            "classification": "CONFIDENTIAL",
        },
        {
            "stage": "succeeded",
            "outcome": "SUCCEEDED",
            "verification_status": "PASSED",
            "classification": "CONFIDENTIAL",
        },
    ]
    assert all(
        set(attributes)
        <= {
            "data.classification",
            "recovery.outcome",
            "recovery.stage",
            "verification.status",
        }
        for attributes in telemetry.span_attributes
    )


def test_run_store_approval_adapter_requires_approved_exact_pending_action_once() -> (
    None
):
    store = InMemoryAgentRunStore()
    run_id = uuid4()
    asyncio.run(store.create(run_id))
    asyncio.run(store.wait_for_approval(run_id, _approval_payload("stored-action")))
    assert asyncio.run(store.claim_resume(run_id, decision="approve")) is not None
    approval_port = AgentRunStoreRecoveryApprovalPort(store)

    assert not asyncio.run(
        approval_port.claim_reference_calibration(
            run_id=uuid4(),
            action_id="stored-action",
            station_id=STATION_ID,
            device_id=DEVICE_ID,
        )
    )
    assert not asyncio.run(
        approval_port.claim_reference_calibration(
            run_id=run_id,
            action_id="stored-action",
            station_id=STATION_ID,
            device_id=DeviceId("POSITION-ENC-03"),
        )
    )
    assert asyncio.run(
        approval_port.claim_reference_calibration(
            run_id=run_id,
            action_id="stored-action",
            station_id=STATION_ID,
            device_id=DEVICE_ID,
        )
    )
    assert not asyncio.run(
        approval_port.claim_reference_calibration(
            run_id=run_id,
            action_id="stored-action",
            station_id=STATION_ID,
            device_id=DEVICE_ID,
        )
    )


def test_run_store_rejected_or_mismatched_approval_cannot_be_claimed() -> None:
    store = InMemoryAgentRunStore()
    run_id = uuid4()
    asyncio.run(store.create(run_id))
    asyncio.run(store.wait_for_approval(run_id, _approval_payload("stored-action")))
    assert asyncio.run(store.claim_resume(run_id, decision="reject")) is not None
    approval_port = AgentRunStoreRecoveryApprovalPort(store)

    assert not asyncio.run(
        approval_port.claim_reference_calibration(
            run_id=run_id,
            action_id="other-action",
            station_id=STATION_ID,
            device_id=DEVICE_ID,
        )
    )


def _execution_service(
    adapter: RecordingPositionEncoderAdapter,
    *,
    approved_bindings: set[tuple[UUID, str, StationId, DeviceId]] | None = None,
    approval_claims: TrustedApprovalClaims | None = None,
) -> HardwareRecoveryExecutionService:
    return HardwareRecoveryExecutionService(
        preparation=HardwareRecoveryPreparationService(physical_devices=adapter),
        physical_devices=adapter,
        approval_claims=approval_claims
        or TrustedApprovalClaims(
            approved_bindings=approved_bindings
            if approved_bindings is not None
            else {(RUN_ID, ACTION_ID, STATION_ID, DEVICE_ID)}
        ),
    )


async def _execute(
    service: HardwareRecoveryExecutionService, *, action_id: str = ACTION_ID
):
    return await service.execute_reference_calibration(
        run_id=RUN_ID,
        action_id=action_id,
        station_id=STATION_ID,
        device_id=DEVICE_ID,
        security_context=DEMO_ENGINEER_SECURITY_CONTEXT,
        mcp_execution_permitted=True,
    )


async def _call_execute(server, *, run_id: str, action_id: str) -> dict[str, object]:  # type: ignore[no-untyped-def]
    result = await server.call_tool(
        "execute_reference_calibration",
        {
            "station_id": "S04",
            "device_id": "POSITION-ENC-02",
            "run_id": run_id,
            "action_id": action_id,
        },
    )
    return result.structured_content


def _approval_payload(action_id: str) -> dict[str, object]:
    return {
        "kind": "action_approval",
        "action": "execute_reference_calibration",
        "action_id": action_id,
        "arguments": {
            "station_id": "S04",
            "device_id": "POSITION-ENC-02",
            "operation_type": "reference_calibration",
            "summary": "Run controlled reference calibration.",
        },
    }
