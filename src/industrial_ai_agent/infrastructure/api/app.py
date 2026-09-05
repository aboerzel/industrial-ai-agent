"""FastAPI routes for the external Industrial AI Agent application boundary."""

from datetime import UTC, datetime
from typing import NoReturn
from uuid import UUID, uuid4

from fastapi import APIRouter, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from industrial_ai_agent.agent.agent_run import AgentRunResult
from industrial_ai_agent.agent.model_egress import (
    DataClassificationBoundaryError,
    ModelEgressDeniedError,
)
from industrial_ai_agent.agent.model_routing import NoEligibleModelError
from industrial_ai_agent.agent.troubleshooting_run_service import (
    AgentRunService,
    McpServiceUnavailableError,
    RunExecution,
)
from industrial_ai_agent.domain.security import DataClassification
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
    HealthResponse,
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

    runs = APIRouter(prefix=API_PREFIX, tags=["runs"])

    @runs.post(
        "/runs",
        response_model=RunResponse,
        responses={
            status.HTTP_403_FORBIDDEN: {"model": ApiErrorResponse},
            status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ApiErrorResponse},
            status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ApiErrorResponse},
        },
        summary="Start one confidential troubleshooting run",
    )
    async def create_run(payload: CreateRunRequest, request: Request) -> RunResponse:
        store = _run_store(request)
        run_id = uuid4()
        await store.create(
            run_id,
            request_text=payload.message,
            data_classification=DataClassification.CONFIDENTIAL,
        )
        # noinspection PyBroadException
        try:
            service = _run_service(request)
            if _persistent_hitl_enabled(service):
                profile, execution = await service.start(payload.message, run_id=run_id)
                await store.bind_execution_context(
                    run_id,
                    data_classification=DataClassification.CONFIDENTIAL,
                    model_profile=profile.name,
                )
                record = await _persist_execution(store, run_id, execution)
                return _to_run_response(record)
            result = await service.run(payload.message)
        except NoEligibleModelError:
            await store.fail(run_id, "no_eligible_model")
            _raise_api_run_error(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="no_eligible_model",
                message="No eligible model is available for this request.",
            )
        except (ModelEgressDeniedError, DataClassificationBoundaryError):
            await store.fail(run_id, "model_egress_denied")
            _raise_api_run_error(
                status_code=status.HTTP_403_FORBIDDEN,
                code="model_egress_denied",
                message="Model execution is not permitted for this request.",
            )
        except McpServiceUnavailableError:
            await store.fail(run_id, "mcp_service_unavailable")
            _raise_api_run_error(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="mcp_service_unavailable",
                message="A required MCP service is unavailable.",
            )
        # noinspection PyBroadException
        except Exception:  # noqa: BLE001 - public API must sanitize unexpected errors.
            await store.fail(run_id, "internal_error")
            _raise_api_run_error(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                code="internal_error",
                message="The agent run could not be completed.",
            )

        if result.model_profile_name is not None:
            await store.bind_execution_context(
                run_id,
                data_classification=DataClassification.CONFIDENTIAL,
                model_profile=result.model_profile_name,
            )
        record = await store.complete(run_id, result)
        return _to_run_response(record)

    @runs.get(
        "/runs/{run_id}",
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
                message="The requested run does not exist.",
            )
        return _to_run_response(record)

    @runs.post(
        "/runs/{run_id}/resume",
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
                message="The requested run does not exist.",
            )
        claimed = await store.claim_resume(run_id, decision=payload.decision.value)
        if claimed is None:
            _raise_api_run_error(
                status_code=status.HTTP_409_CONFLICT,
                code="run_not_waiting_for_approval",
                message="The run is not waiting for approval.",
            )
        service = _run_service(request)
        if not _persistent_hitl_enabled(service) or not claimed.model_profile:
            await store.fail(run_id, "internal_error")
            _raise_api_run_error(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                code="internal_error",
                message="The agent run could not be completed.",
            )
        try:
            execution = await service.resume(
                run_id=run_id,
                model_profile=claimed.model_profile,
                data_classification=claimed.data_classification,
                decision=payload.decision.value,
            )
            return _to_run_response(await _persist_execution(store, run_id, execution))
        except (ModelEgressDeniedError, DataClassificationBoundaryError):
            await store.fail(run_id, "model_egress_denied")
            _raise_api_run_error(
                status_code=status.HTTP_403_FORBIDDEN,
                code="model_egress_denied",
                message="Model execution is not permitted for this request.",
            )
        # noinspection PyBroadException
        except Exception:  # noqa: BLE001
            await store.fail(run_id, "internal_error")
            _raise_api_run_error(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                code="internal_error",
                message="The agent run could not be completed.",
            )

    app.include_router(runs)
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


def _persistent_hitl_enabled(service: AgentRunService) -> bool:
    """Allow an Infrastructure observability decorator around the application service."""
    return bool(getattr(service, "persistent_hitl_enabled", False))


def _to_run_response(record: StoredAgentRun) -> RunResponse:
    result = record.result
    return RunResponse(
        run_id=record.run_id,
        status=record.status,
        answer=sanitize_public_text(result.final_answer)
        if result is not None
        else None,
        tool_calls=_to_tool_calls(result),
        approval_request=_to_approval_request(record.approval_request),
    )


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
