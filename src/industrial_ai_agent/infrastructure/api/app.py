"""FastAPI routes for the external Industrial AI Agent application boundary."""

from datetime import UTC, datetime
from typing import NoReturn
from uuid import UUID, uuid4

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from industrial_ai_agent.agent.agent_run import AgentRunResult
from industrial_ai_agent.agent.model_egress import (
    DataClassificationBoundaryError,
    ModelEgressDeniedError,
)
from industrial_ai_agent.agent.model_routing import NoEligibleModelError
from industrial_ai_agent.agent.response_language import (
    ResponseLanguage,
    detect_response_language,
    user_facing_error_message,
)
from industrial_ai_agent.agent.run_classification_policy import (
    AgentRunClassificationPolicy,
    InternalDiagnosticTarget,
    ResolvedRunPolicy,
    RunClearanceDeniedError,
    resolve_demo_run_profile,
)
from industrial_ai_agent.agent.troubleshooting_run_service import (
    AgentRunService,
    ConversationTurn,
    InternalDiagnosticTargetUnavailableError,
    McpServiceUnavailableError,
    RunExecution,
    internal_diagnostic_message,
)
from industrial_ai_agent.infrastructure.api.demo_security import (
    DemoSecurityContextResolver,
)
from industrial_ai_agent.infrastructure.api.investigation_pdf import (
    render_investigation_pdf,
)
from industrial_ai_agent.infrastructure.api.output_sanitization import (
    sanitize_public_text,
    sanitize_public_value,
)
from industrial_ai_agent.infrastructure.api.run_store import (
    AgentRunStore,
    StoredAgentRun,
)
from industrial_ai_agent.infrastructure.api.schemas import (
    ApiErrorResponse,
    ApprovalRequestResponse,
    CreateRunRequest,
    DataClassificationLabel,
    DemoUserClearance,
    HealthResponse,
    InternalDiagnosticRequest,
    InvestigationResponse,
    InvestigationTurnResponse,
    PublicToolName,
    ResumeRunRequest,
    RunResponse,
    RunStatus,
    ToolCallResponse,
)
from industrial_ai_agent.infrastructure.telemetry import Telemetry, instrument_fastapi

API_PREFIX = "/api/v1"


class _ApiRunError(Exception):
    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message


def create_app(
    run_service: AgentRunService,
    *,
    run_store: AgentRunStore,
    allowed_origins: tuple[str, ...] = (),
    telemetry: Telemetry | None = None,
) -> FastAPI:
    """Create the HTTP adapter with explicitly injected application dependencies."""
    app = FastAPI(
        title="Industrial AI Agent API",
        version="1.0.0",
        description=(
            "Local/demo HTTP boundary for confidential industrial troubleshooting runs."
        ),
    )
    app.state.run_service = run_service
    app.state.run_store = run_store
    app.state.classification_policy = AgentRunClassificationPolicy()
    app.state.demo_security_context_resolver = DemoSecurityContextResolver()
    app.add_exception_handler(_ApiRunError, _api_run_error_handler)
    if allowed_origins:
        # noinspection PyTypeChecker
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(allowed_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
        )

    @app.get(
        "/health",
        response_model=HealthResponse,
        summary="Report API process health",
    )
    async def health() -> HealthResponse:
        return HealthResponse()

    runs = app

    @runs.post(
        f"{API_PREFIX}/runs",
        response_model=RunResponse,
        responses={
            status.HTTP_403_FORBIDDEN: {"model": ApiErrorResponse},
            status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ApiErrorResponse},
            status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ApiErrorResponse},
        },
        summary="Start one server-classified troubleshooting run",
    )
    async def create_run(payload: CreateRunRequest, request: Request) -> RunResponse:
        response_language = detect_response_language(payload.message)
        security_context = _demo_security_context(request).resolve(
            payload.user_clearance
        )
        try:
            policy = _classification_policy(request).resolve(
                resolve_demo_run_profile(
                    payload.message, security_context=security_context
                ),
                security_context=security_context,
            )
        except RunClearanceDeniedError:
            _raise_api_run_error(
                status_code=status.HTTP_404_NOT_FOUND,
                code="requested_data_unavailable",
                message=user_facing_error_message(
                    "requested_data_unavailable", response_language
                ),
            )
        return await _start_run(
            request,
            message=payload.message,
            policy=policy,
            response_language=response_language,
            investigation_id=payload.investigation_id,
        )

    @runs.post(
        f"{API_PREFIX}/diagnostics",
        response_model=RunResponse,
        responses={
            status.HTTP_404_NOT_FOUND: {"model": ApiErrorResponse},
            status.HTTP_403_FORBIDDEN: {"model": ApiErrorResponse},
            status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ApiErrorResponse},
            status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ApiErrorResponse},
        },
        summary="Start one structured read-only internal diagnostic",
    )
    async def create_internal_diagnostic(
        payload: InternalDiagnosticRequest, request: Request
    ) -> RunResponse:
        target = InternalDiagnosticTarget(
            product_id=payload.product_id, station_id=payload.station_id
        )
        try:
            policy = await _run_service(request).resolve_internal_diagnostic(target)
        except InternalDiagnosticTargetUnavailableError:
            _raise_api_run_error(
                status_code=status.HTTP_404_NOT_FOUND,
                code="diagnostic_target_unavailable",
                message=user_facing_error_message(
                    "diagnostic_target_unavailable", ResponseLanguage.EN
                ),
            )
        return await _start_run(
            request,
            message=internal_diagnostic_message(target),
            policy=policy,
            response_language=ResponseLanguage.EN,
        )

    @runs.get(
        f"{API_PREFIX}/runs/{{run_id}}",
        response_model=RunResponse,
        responses={status.HTTP_404_NOT_FOUND: {"model": ApiErrorResponse}},
        summary="Get the persisted record for one agent run",
    )
    async def get_run(run_id: UUID, request: Request) -> RunResponse:
        record = await _run_store(request).get(run_id)
        if record is None:
            _raise_api_run_error(
                status_code=status.HTTP_404_NOT_FOUND,
                code="run_not_found",
                message=user_facing_error_message("run_not_found", ResponseLanguage.EN),
            )
        return _to_run_response(record)

    @runs.get(
        f"{API_PREFIX}/investigations/{{investigation_id}}",
        response_model=InvestigationResponse,
        responses={status.HTTP_404_NOT_FOUND: {"model": ApiErrorResponse}},
        summary="Get the authorized visible history for one investigation",
    )
    async def get_investigation(
        investigation_id: UUID,
        request: Request,
        user_clearance: DemoUserClearance = DemoUserClearance.PUBLIC,
    ) -> InvestigationResponse:
        investigation = await _authorized_investigation(
            request, investigation_id, user_clearance
        )
        if investigation is None:
            _raise_api_run_error(
                status_code=status.HTTP_404_NOT_FOUND,
                code="investigation_not_found",
                message="The requested investigation is not available.",
            )
        return investigation

    @runs.get(
        f"{API_PREFIX}/investigations/{{investigation_id}}/pdf",
        responses={status.HTTP_404_NOT_FOUND: {"model": ApiErrorResponse}},
        summary="Export the authorized visible investigation history as PDF",
    )
    async def export_investigation_pdf(
        investigation_id: UUID,
        request: Request,
        user_clearance: DemoUserClearance = DemoUserClearance.PUBLIC,
    ) -> Response:
        investigation = await _authorized_investigation(
            request, investigation_id, user_clearance
        )
        if investigation is None:
            _raise_api_run_error(
                status_code=status.HTTP_404_NOT_FOUND,
                code="investigation_not_found",
                message="The requested investigation is not available.",
            )
        return Response(
            content=render_investigation_pdf(investigation),
            media_type="application/pdf",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="investigation-{investigation_id}.pdf"'
                )
            },
        )

    @runs.post(
        f"{API_PREFIX}/runs/{{run_id}}/resume",
        response_model=RunResponse,
        responses={
            status.HTTP_404_NOT_FOUND: {"model": ApiErrorResponse},
            status.HTTP_409_CONFLICT: {"model": ApiErrorResponse},
        },
        summary="Approve or reject the pending maintenance action",
    )
    async def resume_run(
        run_id: UUID, payload: ResumeRunRequest, request: Request
    ) -> RunResponse:
        store = _run_store(request)
        existing = await store.get(run_id)
        if existing is None:
            _raise_api_run_error(
                status_code=status.HTTP_404_NOT_FOUND,
                code="run_not_found",
                message=user_facing_error_message("run_not_found", ResponseLanguage.EN),
            )
        claimed = await store.claim_resume(run_id, decision=payload.decision.value)
        if claimed is None:
            _raise_api_run_error(
                status_code=status.HTTP_409_CONFLICT,
                code="run_not_waiting_for_approval",
                message=user_facing_error_message(
                    "run_not_waiting_for_approval", existing.response_language
                ),
            )
        service = _run_service(request)
        if not _persistent_hitl_enabled(service) or not claimed.model_profile:
            await store.fail(run_id, "internal_error")
            _raise_api_run_error(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                code="internal_error",
                message=user_facing_error_message(
                    "internal_error", claimed.response_language
                ),
            )
        try:
            execution = await service.resume(
                run_id=run_id,
                model_profile=claimed.model_profile,
                data_classification=claimed.data_classification,
                run_profile=claimed.run_profile,
                decision=payload.decision.value,
            )
            return _to_run_response(await _persist_execution(store, run_id, execution))
        except (ModelEgressDeniedError, DataClassificationBoundaryError):
            await store.fail(run_id, "model_egress_denied")
            _raise_api_run_error(
                status_code=status.HTTP_403_FORBIDDEN,
                code="model_egress_denied",
                message=user_facing_error_message(
                    "model_egress_denied", claimed.response_language
                ),
            )
        # noinspection PyBroadException
        except Exception:  # noqa: BLE001
            await store.fail(run_id, "internal_error")
            _raise_api_run_error(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                code="internal_error",
                message=user_facing_error_message(
                    "internal_error", claimed.response_language
                ),
            )

    if telemetry is not None:
        instrument_fastapi(app, telemetry)

        @app.on_event("shutdown")
        async def flush_telemetry() -> None:
            telemetry.shutdown()

    return app


async def _api_run_error_handler(
    _: Request,
    error: Exception,
) -> JSONResponse:
    if not isinstance(error, _ApiRunError):
        raise TypeError("Unexpected API exception handler input")
    return JSONResponse(
        status_code=error.status_code,
        content=ApiErrorResponse(code=error.code, message=error.message).model_dump(),
    )


def _run_service(request: Request) -> AgentRunService:
    return request.app.state.run_service


def _run_store(request: Request) -> AgentRunStore:
    return request.app.state.run_store


def _classification_policy(request: Request) -> AgentRunClassificationPolicy:
    return request.app.state.classification_policy


def _demo_security_context(request: Request) -> DemoSecurityContextResolver:
    return request.app.state.demo_security_context_resolver


def _persistent_hitl_enabled(service: AgentRunService) -> bool:
    """Allow an Infrastructure observability decorator around the application service."""
    return bool(getattr(service, "persistent_hitl_enabled", False))


async def _start_run(
    request: Request,
    *,
    message: str,
    policy: ResolvedRunPolicy,
    response_language: ResponseLanguage,
    investigation_id: UUID | None = None,
) -> RunResponse:
    store = _run_store(request)
    run_id = uuid4()
    previous_runs = (
        await store.list_investigation(investigation_id)
        if investigation_id is not None
        else ()
    )
    await store.create(
        run_id,
        investigation_id=investigation_id,
        request_text=message,
        data_classification=policy.data_classification,
        run_profile=policy.run_profile,
        response_language=response_language,
    )
    service = _run_service(request)
    conversation_context = _conversation_context(previous_runs, policy)
    try:
        if _persistent_hitl_enabled(service):
            profile, execution = await service.start(
                message,
                run_id=run_id,
                run_policy=policy,
                response_language=response_language,
                conversation_context=conversation_context,
            )
            await store.bind_execution_context(
                run_id,
                data_classification=policy.data_classification,
                run_profile=policy.run_profile,
                model_profile=profile.name,
            )
            return _to_run_response(await _persist_execution(store, run_id, execution))
        if conversation_context:
            result = await service.run_with_policy(
                message,
                run_policy=policy,
                response_language=response_language,
                conversation_context=conversation_context,
            )
        else:
            result = await service.run_with_policy(
                message, run_policy=policy, response_language=response_language
            )
    except NoEligibleModelError:
        await store.fail(run_id, "no_eligible_model")
        _raise_api_run_error(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="no_eligible_model",
            message=user_facing_error_message("no_eligible_model", response_language),
        )
    except (ModelEgressDeniedError, DataClassificationBoundaryError):
        await store.fail(run_id, "model_egress_denied")
        _raise_api_run_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="model_egress_denied",
            message=user_facing_error_message("model_egress_denied", response_language),
        )
    except McpServiceUnavailableError:
        await store.fail(run_id, "mcp_service_unavailable")
        _raise_api_run_error(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="mcp_service_unavailable",
            message=user_facing_error_message(
                "mcp_service_unavailable", response_language
            ),
        )
    except Exception:  # noqa: BLE001 - public API must sanitize unexpected errors.
        await store.fail(run_id, "internal_error")
        _raise_api_run_error(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="internal_error",
            message=user_facing_error_message("internal_error", response_language),
        )
    if result.model_profile_name is not None:
        await store.bind_execution_context(
            run_id,
            data_classification=policy.data_classification,
            run_profile=policy.run_profile,
            model_profile=result.model_profile_name,
        )
    return _to_run_response(await store.complete(run_id, result))


def _to_run_response(record: StoredAgentRun) -> RunResponse:
    result = record.result
    return RunResponse(
        run_id=record.run_id,
        investigation_id=record.investigation_id,
        investigation_sequence=record.investigation_sequence,
        status=record.status,
        data_classification=DataClassificationLabel[record.data_classification.name],
        answer=sanitize_public_text(result.final_answer)
        if result is not None
        else None,
        tool_calls=_to_tool_calls(result),
        approval_request=_to_approval_request(record.approval_request),
    )


async def _authorized_investigation(
    request: Request,
    investigation_id: UUID,
    user_clearance: DemoUserClearance,
) -> InvestigationResponse | None:
    security_context = _demo_security_context(request).resolve(user_clearance)
    records = await _run_store(request).list_investigation(investigation_id)
    visible = tuple(
        record
        for record in records
        if int(record.data_classification) <= int(security_context.clearance)
    )
    if not visible:
        return None
    turns = tuple(_to_investigation_turn(record) for record in visible)
    return InvestigationResponse(
        investigation_id=investigation_id,
        created_at=_as_iso(visible[0].created_at),
        run_count=len(turns),
        tool_call_count=sum(len(turn.tool_calls) for turn in turns),
        status=_investigation_status(visible),
        turns=turns,
    )


def _to_investigation_turn(record: StoredAgentRun) -> InvestigationTurnResponse:
    result = record.result
    return InvestigationTurnResponse(
        run_id=record.run_id,
        sequence=record.investigation_sequence,
        status=record.status,
        data_classification=DataClassificationLabel[record.data_classification.name],
        response_language=record.response_language.value,
        request=sanitize_public_text(record.request_text) or "",
        answer=sanitize_public_text(result.final_answer) if result else None,
        tool_calls=_to_tool_calls(result),
        created_at=_as_iso(record.created_at),
        updated_at=_as_iso(record.updated_at),
        approval_request=_to_approval_request(record.approval_request),
    )


def _conversation_context(
    records: tuple[StoredAgentRun, ...], policy: ResolvedRunPolicy
) -> tuple[ConversationTurn, ...]:
    eligible = [
        record
        for record in records
        if int(record.data_classification) <= int(policy.data_classification)
    ]
    return tuple(
        ConversationTurn(
            user_request=record.request_text,
            agent_answer=record.result.final_answer if record.result else None,
        )
        for record in eligible[-4:]
    )


def _investigation_status(records: tuple[StoredAgentRun, ...]) -> str:
    if any(
        record.status in {RunStatus.RUNNING, RunStatus.WAITING_FOR_APPROVAL}
        for record in records
    ):
        return "in_progress"
    if all(record.status is RunStatus.SUCCESS for record in records):
        return "completed"
    return "completed_with_attention"


def _as_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


async def _persist_execution(
    store: AgentRunStore, run_id: UUID, execution: RunExecution
) -> StoredAgentRun:
    if execution.result is not None:
        return await store.complete(run_id, execution.result)
    approval = execution.approval
    if approval is None:
        raise RuntimeError("Run execution was incomplete")
    record = await store.get(run_id)
    if record is None or record.model_profile is None:
        raise RuntimeError("Approval requires a bound execution context")
    return await store.wait_for_approval(
        run_id,
        {
            "action": approval.action,
            "summary": approval.summary,
            "arguments": approval.arguments,
            "classification": record.data_classification.name,
            "model_profile": record.model_profile,
            "status": RunStatus.WAITING_FOR_APPROVAL.value,
            "created_at": datetime.now(UTC).isoformat(),
        },
    )


def _to_approval_request(
    payload: dict[str, object] | None,
) -> ApprovalRequestResponse | None:
    if payload is None:
        return None
    return ApprovalRequestResponse.model_validate(sanitize_public_value(payload))


def _to_tool_calls(result: AgentRunResult | None) -> tuple[ToolCallResponse, ...]:
    if result is None:
        return ()
    return tuple(
        ToolCallResponse(
            tool=PublicToolName(call.tool),
            arguments=sanitize_public_value(call.arguments),
        )
        for call in result.executed_tool_calls
    )


def _raise_api_run_error(
    *,
    status_code: int,
    code: str,
    message: str,
) -> NoReturn:
    raise _ApiRunError(status_code=status_code, code=code, message=message)
