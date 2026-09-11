"""Bounded Hardware MCP transport for position-reference recovery preparation."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from industrial_ai_agent.application.hardware_recovery import (
    HardwareRecoveryExecutionService,
    HardwareRecoveryNotAccessibleError,
    HardwareRecoveryPreparationService,
    PositionReferenceStatus,
    ReferenceCalibrationPreparation,
)
from industrial_ai_agent.application.mcp_access import McpPermission
from industrial_ai_agent.domain.closed_loop_recovery import (
    PreconditionEvaluation,
    RecoveryPrecondition,
    VerificationCriterion,
)
from industrial_ai_agent.domain.physical_device import DeviceId
from industrial_ai_agent.domain.product_history import StationId
from industrial_ai_agent.domain.security import (
    DEMO_ENGINEER_SECURITY_CONTEXT,
    SecurityContext,
)
from industrial_ai_agent.infrastructure.mcp_access_control import (
    McpHttpAccessControl,
    install_mcp_http_access_control,
)
from industrial_ai_agent.infrastructure.mcp_schema_validation import (
    require_strict_mcp_tool_arguments,
)
from industrial_ai_agent.infrastructure.simulated_position_encoder_adapter import (
    SimulatedPositionEncoderAdapter,
)
from industrial_ai_agent.infrastructure.telemetry import Telemetry

HARDWARE_MCP_SERVER_NAME = "hardware_mcp"
HARDWARE_MCP_SERVER_VERSION = "0.1.0"

StationIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^S[0-9]{2,3}$"),
]
DeviceIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[A-Z][A-Z0-9-]{2,63}$"),
]
RunIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
            r"[0-9a-f]{4}-[0-9a-f]{12}$"
        ),
    ),
]
ActionIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]

_HARDWARE_TOOL_PERMISSIONS = {
    "get_position_reference_status": McpPermission.READ_HARDWARE_STATUS,
    "prepare_reference_calibration": McpPermission.PREPARE_HARDWARE_RECOVERY,
    "execute_reference_calibration": McpPermission.EXECUTE_HARDWARE_RECOVERY,
}


class _McpModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _PositionReferenceStatusProjection(_McpModel):
    station_id: str
    device_id: str
    connection_state: str
    operational_state: str | None
    reference_valid: bool | None
    position_deviation_mm: float | None
    configured_tolerance_mm: float = Field(ge=0)
    station_mode: str | None
    axis_motion_state: str | None
    product_present: bool | None
    calibration_supported: bool
    classification: str


class _PreconditionProjection(_McpModel):
    condition_type: str
    description: str


class _PreconditionEvaluationProjection(_McpModel):
    condition_type: str
    status: str
    observed_value: str | bool | None


class _EvidenceProjection(_McpModel):
    reference: str
    summary: str


class _VerificationCriterionProjection(_McpModel):
    criterion_type: str
    maximum_abs_deviation: float | None


class _ReferenceCalibrationPreparationProjection(_McpModel):
    station_id: str
    device_id: str
    problem: str
    evidence: tuple[_EvidenceProjection, ...]
    proposed_operation: str
    action_risk_class: str
    preconditions: tuple[_PreconditionProjection, ...]
    precondition_evaluations: tuple[_PreconditionEvaluationProjection, ...]
    requires_approval: bool
    expected_effect: str
    verification_plan: tuple[_VerificationCriterionProjection, ...]
    classification: str


class _VerificationEvidenceProjection(_McpModel):
    criterion_type: str
    passed: bool
    observed_value: bool | float


class _RecoveryResultProjection(_McpModel):
    station_id: str
    device_id: str
    action_executed: bool
    operation_status: str | None
    precondition_evaluations: tuple[_PreconditionEvaluationProjection, ...]
    verification_status: str
    verification_evidence: tuple[_VerificationEvidenceProjection, ...]
    recovery_outcome: str


def create_hardware_mcp_server(
    *,
    recovery_preparation: HardwareRecoveryPreparationService,
    recovery_execution: HardwareRecoveryExecutionService | None = None,
    access_control: McpHttpAccessControl | None = None,
    default_security_context: SecurityContext = DEMO_ENGINEER_SECURITY_CONTEXT,
    telemetry: Telemetry | None = None,
) -> MCPServer:
    """Expose bounded status and recovery preparation over injected application logic."""
    if not isinstance(default_security_context, SecurityContext):
        raise TypeError("default_security_context must be a SecurityContext")
    server = MCPServer(
        name=HARDWARE_MCP_SERVER_NAME,
        version=HARDWARE_MCP_SERVER_VERSION,
        description="Bounded position-reference status and recovery-preparation tools.",
    )

    @server.tool(
        name="get_position_reference_status",
        description="Get bounded position-reference status for one authorized device.",
        structured_output=True,
        annotations=ToolAnnotations(read_only_hint=True),
    )
    def get_position_reference_status(
        station_id: StationIdentifier,
        device_id: DeviceIdentifier,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        security_context = _security_context_for_request(
            ctx=ctx,
            access_control=access_control,
            tool_name="get_position_reference_status",
            default_security_context=default_security_context,
        )
        try:
            result = recovery_preparation.get_position_reference_status(
                station_id=_station_id(station_id),
                device_id=_device_id(device_id),
                security_context=security_context,
            )
        except (HardwareRecoveryNotAccessibleError, TypeError, ValueError) as error:
            raise LookupError(
                "Position-reference information is unavailable"
            ) from error
        return _project_status(
            result, recovery_preparation.position_deviation_tolerance_mm
        ).model_dump(mode="json")

    @server.tool(
        name="prepare_reference_calibration",
        description=(
            "Prepare a controlled reference-calibration proposal for one authorized "
            "device. This tool never executes calibration."
        ),
        structured_output=True,
        annotations=ToolAnnotations(read_only_hint=True),
    )
    def prepare_reference_calibration(
        station_id: StationIdentifier,
        device_id: DeviceIdentifier,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        security_context = _security_context_for_request(
            ctx=ctx,
            access_control=access_control,
            tool_name="prepare_reference_calibration",
            default_security_context=default_security_context,
        )
        try:
            result = recovery_preparation.prepare_reference_calibration(
                station_id=_station_id(station_id),
                device_id=_device_id(device_id),
                security_context=security_context,
            )
        except (HardwareRecoveryNotAccessibleError, TypeError, ValueError) as error:
            raise LookupError(
                "Position-reference information is unavailable"
            ) from error
        _record_recovery_lifecycle(
            telemetry=telemetry,
            stage="prepared",
            outcome="NOT_EXECUTED",
            verification_status="NOT_RUN",
            classification=result.classification.name,
        )
        return _project_preparation(result).model_dump(mode="json")

    @server.tool(
        name="execute_reference_calibration",
        description=(
            "Execute one server-approved reference calibration. Approval and execution "
            "identifiers are injected by the trusted HITL resume path, never by the model."
        ),
        structured_output=True,
        annotations=ToolAnnotations(read_only_hint=False),
    )
    async def execute_reference_calibration(
        station_id: StationIdentifier,
        device_id: DeviceIdentifier,
        run_id: RunIdentifier,
        action_id: ActionIdentifier,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        security_context = _security_context_for_request(
            ctx=ctx,
            access_control=access_control,
            tool_name="execute_reference_calibration",
            default_security_context=default_security_context,
        )
        if recovery_execution is None:
            raise LookupError("Position-reference information is unavailable")
        try:
            _record_recovery_lifecycle(
                telemetry=telemetry,
                stage="action_attempted",
                outcome="PENDING",
                verification_status="NOT_RUN",
                classification="CONFIDENTIAL",
            )
            result = await recovery_execution.execute_reference_calibration(
                run_id=UUID(run_id),
                action_id=action_id,
                station_id=_station_id(station_id),
                device_id=_device_id(device_id),
                security_context=security_context,
                mcp_execution_permitted=True,
            )
        except (HardwareRecoveryNotAccessibleError, TypeError, ValueError) as error:
            raise LookupError(
                "Position-reference information is unavailable"
            ) from error
        _record_recovery_result(telemetry=telemetry, result=result)
        return _project_recovery_result(result).model_dump(mode="json")

    for tool_name in _HARDWARE_TOOL_PERMISSIONS:
        require_strict_mcp_tool_arguments(server, tool_name)
    if access_control is not None:
        install_mcp_http_access_control(server, access_control)
    return server


def create_demo_hardware_mcp_server(
    *,
    access_control: McpHttpAccessControl | None = None,
    default_security_context: SecurityContext = DEMO_ENGINEER_SECURITY_CONTEXT,
    telemetry: Telemetry | None = None,
) -> MCPServer:
    """Compose the local deterministic S04 demonstrator at the Infrastructure edge."""
    adapter = SimulatedPositionEncoderAdapter()
    return create_hardware_mcp_server(
        recovery_preparation=HardwareRecoveryPreparationService(
            physical_devices=adapter
        ),
        access_control=access_control,
        default_security_context=default_security_context,
        telemetry=telemetry,
    )


def _security_context_for_request(
    *,
    ctx: Context | None,
    access_control: McpHttpAccessControl | None,
    tool_name: str,
    default_security_context: SecurityContext,
) -> SecurityContext:
    if access_control is None:
        return default_security_context
    if ctx is None:
        raise PermissionError("MCP authentication failed")
    access_context = access_control.access_context_from_headers(ctx.headers)
    access_control.authorize_tool(access_context, tool_name)
    return access_context.security_context


def _station_id(value: str) -> StationId:
    return StationId(value)


def _device_id(value: str) -> DeviceId:
    return DeviceId(value)


def _project_status(
    result: PositionReferenceStatus, tolerance_mm: float
) -> _PositionReferenceStatusProjection:
    state = result.state
    assert state.station_id is not None
    return _PositionReferenceStatusProjection(
        station_id=state.station_id.value,
        device_id=state.device_id.value,
        connection_state=state.connection_state.value,
        operational_state=(
            state.operational_state.value
            if state.operational_state is not None
            else None
        ),
        reference_valid=state.reference_valid,
        position_deviation_mm=(
            round(state.position_deviation, 3)
            if state.position_deviation is not None
            else None
        ),
        configured_tolerance_mm=tolerance_mm,
        station_mode=state.station_mode.value
        if state.station_mode is not None
        else None,
        axis_motion_state=(
            state.axis_motion_state.value
            if state.axis_motion_state is not None
            else None
        ),
        product_present=state.product_present,
        calibration_supported=result.calibration_supported,
        classification=result.classification.name,
    )


def _project_preparation(
    result: ReferenceCalibrationPreparation,
) -> _ReferenceCalibrationPreparationProjection:
    proposal = result.proposal
    assert proposal.target.station_id is not None
    return _ReferenceCalibrationPreparationProjection(
        station_id=proposal.target.station_id.value,
        device_id=proposal.target.device_id.value,
        problem=proposal.problem,
        evidence=tuple(
            _EvidenceProjection(reference=evidence.reference, summary=evidence.summary)
            for evidence in proposal.evidence
        ),
        proposed_operation=proposal.proposed_action.operation_type.value,
        action_risk_class=proposal.proposed_action.risk_class.value,
        preconditions=tuple(
            _project_precondition(precondition)
            for precondition in proposal.preconditions
        ),
        precondition_evaluations=tuple(
            _project_precondition_evaluation(evaluation)
            for evaluation in result.precondition_evaluations
        ),
        requires_approval=proposal.requires_approval,
        expected_effect=proposal.expected_effect,
        verification_plan=tuple(
            _project_verification_criterion(criterion)
            for criterion in proposal.verification_plan.criteria
        ),
        classification=result.classification.name,
    )


def _project_precondition(
    precondition: RecoveryPrecondition,
) -> _PreconditionProjection:
    return _PreconditionProjection(
        condition_type=precondition.condition_type.value,
        description=precondition.description,
    )


def _project_precondition_evaluation(
    evaluation: PreconditionEvaluation,
) -> _PreconditionEvaluationProjection:
    observed_value = evaluation.observed_value
    return _PreconditionEvaluationProjection(
        condition_type=evaluation.precondition.condition_type.value,
        status=evaluation.status.value,
        observed_value=(
            observed_value.value if hasattr(observed_value, "value") else observed_value
        ),
    )


def _project_verification_criterion(
    criterion: VerificationCriterion,
) -> _VerificationCriterionProjection:
    return _VerificationCriterionProjection(
        criterion_type=criterion.criterion_type.value,
        maximum_abs_deviation=criterion.maximum_abs_deviation,
    )


def _project_recovery_result(result: Any) -> _RecoveryResultProjection:
    pre_action_state = result.pre_action_state
    if pre_action_state is None or pre_action_state.station_id is None:
        raise ValueError("Recovery result does not contain a bounded target")
    return _RecoveryResultProjection(
        station_id=pre_action_state.station_id.value,
        device_id=pre_action_state.device_id.value,
        action_executed=result.action_executed,
        operation_status=(
            result.operation_result.status.value
            if result.operation_result is not None
            else None
        ),
        precondition_evaluations=tuple(
            _project_precondition_evaluation(evaluation)
            for evaluation in result.precondition_evaluations
        ),
        verification_status=result.verification.status.value,
        verification_evidence=tuple(
            _VerificationEvidenceProjection(
                criterion_type=evidence.criterion.criterion_type.value,
                passed=evidence.passed,
                observed_value=evidence.observed_value,
            )
            for evidence in result.verification.evidence
        ),
        recovery_outcome=result.outcome.value,
    )


def _record_recovery_result(*, telemetry: Telemetry | None, result: Any) -> None:
    if result.outcome.value == "SUCCEEDED":
        stage = "succeeded"
    elif result.outcome.value == "BLOCKED":
        stage = "blocked"
    elif result.operation_result is not None and not result.action_executed:
        stage = "action_failed"
    else:
        stage = "verification_failed"
    _record_recovery_lifecycle(
        telemetry=telemetry,
        stage=stage,
        outcome=result.outcome.value,
        verification_status=result.verification.status.value,
        classification="CONFIDENTIAL",
    )


def _record_recovery_lifecycle(
    *,
    telemetry: Telemetry | None,
    stage: str,
    outcome: str,
    verification_status: str,
    classification: str,
) -> None:
    if telemetry is not None:
        telemetry.set_current_span_attributes(
            {
                "recovery.stage": stage,
                "recovery.outcome": outcome,
                "verification.status": verification_status,
                "data.classification": classification,
            }
        )
        telemetry.record_recovery_lifecycle(
            stage=stage,
            outcome=outcome,
            verification_status=verification_status,
            classification=classification,
        )
