"""FastAPI routes for the external Industrial AI Agent application boundary."""

import asyncio
import logging
from datetime import UTC, datetime
from typing import NoReturn
from uuid import UUID, uuid4

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from industrial_ai_agent.agent.agent_run import AgentRunResult, DocumentReference
from industrial_ai_agent.agent.llm import LLMProviderError
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
from industrial_ai_agent.application.document_content import (
    AuthorizedDocumentContent,
    AuthorizedDocumentContentReader,
)
from industrial_ai_agent.domain.security import SecurityContext
from industrial_ai_agent.infrastructure.api.demo_security import (
    DemoSecurityContextResolver,
)
from industrial_ai_agent.infrastructure.api.failure_diagnostics import summarize_failure
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
    InvestigationStepResponse,
    InvestigationTurnResponse,
    PublicToolName,
    ResumeRunRequest,
    RunResponse,
    RunStatus,
    ToolCallResponse,
)
from industrial_ai_agent.infrastructure.telemetry import Telemetry, instrument_fastapi

API_PREFIX = "/api/v1"
_FAILURE_LOGGER = logging.getLogger("industrial_ai_agent.api.failure_diagnostics")
_PERSISTED_RUN_ERROR_CODES = frozenset(
    {
        "internal_error",
        "llm_provider_unavailable",
        "llm_quota_exceeded",
        "llm_rate_limit",
        "mcp_service_unavailable",
        "model_egress_denied",
        "no_eligible_model",
        "agent_execution_timeout",
        "recovery_incomplete",
        "recovery_blocked",
        "recovery_failed",
    }
)
_SAFE_PROVIDER_ERROR_TYPES = frozenset(
    {"APIConnectionError", "APIStatusError", "RateLimitError"}
)


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
    document_content_reader: AuthorizedDocumentContentReader | None = None,
    execution_timeout_seconds: float = 60.0,
) -> FastAPI:
    """Create the HTTP adapter with explicitly injected application dependencies."""
    app = FastAPI(
        title="Industrial AI Agent API",
        version="1.0.0",
        description=(
            "Local/demo HTTP boundary for confidential industrial troubleshooting runs."
        ),
    )
    if execution_timeout_seconds <= 0:
        raise ValueError("execution_timeout_seconds must be positive")
    app.state.run_service = run_service
    app.state.execution_timeout_seconds = execution_timeout_seconds
    app.state.run_store = run_store
    app.state.telemetry = telemetry
    app.state.classification_policy = AgentRunClassificationPolicy()
    app.state.demo_security_context_resolver = DemoSecurityContextResolver()
    app.state.document_content_reader = document_content_reader
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
        # API clients that do not send a language retain the established deterministic
        # fallback. Browser clients always send this field explicitly.
        response_language = payload.response_language or detect_response_language(
            payload.message
        )
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
            document_security_context=security_context,
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
            document_security_context=_demo_security_context(request).resolve(
                DemoUserClearance.INTERNAL
            ),
        )

    @runs.get(
        f"{API_PREFIX}/runs/{{run_id}}",
        response_model=RunResponse,
        responses={status.HTTP_404_NOT_FOUND: {"model": ApiErrorResponse}},
        summary="Get the persisted record for one agent run",
    )
    async def get_run(
        run_id: UUID,
        request: Request,
        user_clearance: DemoUserClearance = DemoUserClearance.PUBLIC,
    ) -> RunResponse:
        record = await _run_store(request).get(run_id)
        if record is None:
            _raise_api_run_error(
                status_code=status.HTTP_404_NOT_FOUND,
                code="run_not_found",
                message=user_facing_error_message("run_not_found", ResponseLanguage.EN),
            )
        return _to_run_response(
            record,
            documents=_authorized_documents_for_result(
                request,
                record.result,
                _demo_security_context(request).resolve(user_clearance),
            ),
        )

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

    @runs.get(
        f"{API_PREFIX}/documents/{{document_id}}",
        responses={status.HTTP_404_NOT_FOUND: {"model": ApiErrorResponse}},
        summary="Open one currently authorized cataloged document",
    )
    async def open_document(
        document_id: str,
        request: Request,
        user_clearance: DemoUserClearance = DemoUserClearance.PUBLIC,
    ) -> Response:
        document = _authorized_document_content(request, document_id, user_clearance)
        return _document_response(document, disposition="inline")

    @runs.get(
        f"{API_PREFIX}/documents/{{document_id}}/download",
        responses={status.HTTP_404_NOT_FOUND: {"model": ApiErrorResponse}},
        summary="Download one currently authorized cataloged document",
    )
    async def download_document(
        document_id: str,
        request: Request,
        user_clearance: DemoUserClearance = DemoUserClearance.PUBLIC,
    ) -> Response:
        document = _authorized_document_content(request, document_id, user_clearance)
        return _document_response(document, disposition="attachment")

    @runs.post(
        f"{API_PREFIX}/runs/{{run_id}}/resume",
        response_model=RunResponse,
        responses={
            status.HTTP_404_NOT_FOUND: {"model": ApiErrorResponse},
            status.HTTP_409_CONFLICT: {"model": ApiErrorResponse},
            status.HTTP_504_GATEWAY_TIMEOUT: {"model": ApiErrorResponse},
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
            execution = await asyncio.wait_for(
                service.resume(
                    run_id=run_id,
                    model_profile=claimed.model_profile,
                    data_classification=claimed.data_classification,
                    run_profile=claimed.run_profile,
                    decision=payload.decision.value,
                ),
                timeout=_execution_timeout_seconds(request),
            )
            return _to_run_response(await _persist_execution(store, run_id, execution))
        except TimeoutError:
            await store.fail(run_id, "agent_execution_timeout")
            _raise_api_run_error(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                code="agent_execution_timeout",
                message=user_facing_error_message(
                    "agent_execution_timeout", claimed.response_language
                ),
            )
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
        except Exception as error:  # noqa: BLE001 - public API must sanitize failures.
            provider_error = _provider_error_from(error)
            if provider_error is not None:
                await store.fail(run_id, provider_error.code)
                _record_llm_provider_failure(
                    run_id=run_id,
                    error=provider_error,
                    telemetry=_telemetry(request),
                )
                _raise_api_run_error(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    code=provider_error.code,
                    message=user_facing_error_message(
                        provider_error.code, claimed.response_language
                    ),
                )
            _record_internal_failure(
                run_id=run_id, error=error, telemetry=_telemetry(request)
            )
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


def _telemetry(request: Request) -> Telemetry | None:
    return request.app.state.telemetry


def _classification_policy(request: Request) -> AgentRunClassificationPolicy:
    return request.app.state.classification_policy


def _execution_timeout_seconds(request: Request) -> float:
    return request.app.state.execution_timeout_seconds


def _demo_security_context(request: Request) -> DemoSecurityContextResolver:
    return request.app.state.demo_security_context_resolver


def _authorized_document_content(
    request: Request,
    document_id: str,
    user_clearance: DemoUserClearance,
) -> AuthorizedDocumentContent:
    reader: AuthorizedDocumentContentReader | None = (
        request.app.state.document_content_reader
    )
    document = (
        reader.get_document(
            document_id, _demo_security_context(request).resolve(user_clearance)
        )
        if reader is not None
        else None
    )
    if document is None:
        _raise_api_run_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="document_not_available",
            message="The requested document is not available.",
        )
    return document


def _authorized_documents_for_result(
    request: Request,
    result: AgentRunResult | None,
    security_context: SecurityContext,
) -> tuple[DocumentReference, ...]:
    """Publish only run references whose current RLS-visible content is usable."""
    if result is None:
        return ()
    reader: AuthorizedDocumentContentReader | None = (
        request.app.state.document_content_reader
    )
    if reader is None:
        return ()
    return tuple(
        reference
        for reference in result.documents
        if reader.get_document(reference.document_id, security_context) is not None
    )


def _with_authorized_documents(
    result: AgentRunResult,
    documents: tuple[DocumentReference, ...],
) -> AgentRunResult:
    return result.model_copy(update={"documents": documents})


def _document_response(
    document: AuthorizedDocumentContent, *, disposition: str
) -> Response:
    return Response(
        content=document.content,
        media_type=document.media_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{document.filename}"'
        },
    )


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
    document_security_context: SecurityContext,
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
            profile, execution = await asyncio.wait_for(
                service.start(
                    message,
                    run_id=run_id,
                    run_policy=policy,
                    response_language=response_language,
                    conversation_context=conversation_context,
                ),
                timeout=_execution_timeout_seconds(request),
            )
            await store.bind_execution_context(
                run_id,
                data_classification=policy.data_classification,
                run_profile=policy.run_profile,
                model_profile=profile.name,
            )
            return _to_run_response(
                await _persist_execution(
                    store,
                    run_id,
                    execution,
                    documents=_authorized_documents_for_result(
                        request, execution.result, document_security_context
                    ),
                )
            )
        if conversation_context:
            result = await asyncio.wait_for(
                service.run_with_policy(
                    message,
                    run_policy=policy,
                    response_language=response_language,
                    conversation_context=conversation_context,
                ),
                timeout=_execution_timeout_seconds(request),
            )
        else:
            result = await asyncio.wait_for(
                service.run_with_policy(
                    message, run_policy=policy, response_language=response_language
                ),
                timeout=_execution_timeout_seconds(request),
            )
    except TimeoutError:
        return _to_run_response(await store.fail(run_id, "agent_execution_timeout"))
    except NoEligibleModelError:
        return _to_run_response(await store.fail(run_id, "no_eligible_model"))
    except (ModelEgressDeniedError, DataClassificationBoundaryError):
        await store.fail(run_id, "model_egress_denied")
        _raise_api_run_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="model_egress_denied",
            message=user_facing_error_message("model_egress_denied", response_language),
        )
    except McpServiceUnavailableError:
        return _to_run_response(await store.fail(run_id, "mcp_service_unavailable"))
    except Exception as error:  # noqa: BLE001 - public API must sanitize unexpected errors.
        provider_error = _provider_error_from(error)
        if provider_error is not None:
            failed_record = await store.fail(run_id, provider_error.code)
            _record_llm_provider_failure(
                run_id=run_id,
                error=provider_error,
                telemetry=_telemetry(request),
            )
            return _to_run_response(failed_record)
        _record_internal_failure(
            run_id=run_id, error=error, telemetry=_telemetry(request)
        )
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
    filtered_result = _with_authorized_documents(
        result,
        _authorized_documents_for_result(request, result, document_security_context),
    )
    return _to_run_response(await store.complete(run_id, filtered_result))


def _record_internal_failure(
    *, run_id: UUID, error: BaseException, telemetry: Telemetry | None
) -> None:
    """Log only bounded diagnostics for an unexpected LangGraph/runtime failure."""
    diagnostics = summarize_failure(error)
    exception_group = (
        type(error).__name__ if isinstance(error, BaseExceptionGroup) else None
    )
    for index, diagnostic in enumerate(diagnostics):
        _FAILURE_LOGGER.error(
            "agent.run.failed run_id=%s exception_group=%s inner_index=%d "
            "exception_type=%s operation=%s error_code=%s sanitized_reason=%s",
            run_id,
            exception_group,
            index,
            diagnostic.exception_type,
            diagnostic.operation,
            diagnostic.safe_error_code,
            diagnostic.sanitized_reason,
        )
    if telemetry is not None and diagnostics:
        primary = diagnostics[0]
        telemetry.set_current_span_attributes(
            {
                "error.type": primary.exception_type,
                "error.code": primary.safe_error_code,
                "error.stage": primary.operation,
            }
        )


def _record_llm_provider_failure(
    *, run_id: UUID, error: LLMProviderError, telemetry: Telemetry | None
) -> None:
    """Record only the bounded provider category, never its response payload."""
    error_type = (
        error.provider_error_type
        if error.provider_error_type in _SAFE_PROVIDER_ERROR_TYPES
        else "ProviderError"
    )
    _FAILURE_LOGGER.warning(
        "agent.run.provider_failure run_id=%s error_code=%s error_type=%s",
        run_id,
        error.code,
        error_type,
    )
    if telemetry is not None:
        telemetry.set_current_span_attributes(
            {
                "error.code": error.code,
                "error.stage": error.error_stage,
                "error.type": error_type,
            }
        )


def _provider_error_from(error: BaseException) -> LLMProviderError | None:
    """Accept a provider category only when every grouped leaf is that category."""
    if isinstance(error, LLMProviderError):
        return error
    if not isinstance(error, BaseExceptionGroup):
        return None
    leaves = _exception_leaves(error)
    provider_errors = [leaf for leaf in leaves if isinstance(leaf, LLMProviderError)]
    if (
        not provider_errors
        or len(provider_errors) != len(leaves)
        or len({provider_error.code for provider_error in provider_errors}) != 1
    ):
        return None
    return provider_errors[0]


def _exception_leaves(error: BaseException) -> tuple[BaseException, ...]:
    if not isinstance(error, BaseExceptionGroup):
        return (error,)
    return tuple(
        leaf for nested in error.exceptions for leaf in _exception_leaves(nested)
    )


def _to_run_response(
    record: StoredAgentRun,
    *,
    documents: tuple[DocumentReference, ...] | None = None,
) -> RunResponse:
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
        recovery_outcome=result.recovery_outcome if result is not None else None,
        investigation_steps=_to_investigation_steps(result),
        next_steps=_to_next_steps(result),
        identifiers=_to_identifiers(result),
        documents=_to_documents(documents if documents is not None else result),
        tool_calls=_to_tool_calls(result),
        error=_to_persisted_run_error(record),
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
    turns = tuple(
        _to_investigation_turn(
            record,
            documents=_authorized_documents_for_result(
                request, record.result, security_context
            ),
        )
        for record in visible
    )
    return InvestigationResponse(
        investigation_id=investigation_id,
        created_at=_as_iso(visible[0].created_at),
        run_count=len(turns),
        tool_call_count=sum(len(turn.tool_calls) for turn in turns),
        status=_investigation_status(visible),
        turns=turns,
    )


def _to_investigation_turn(
    record: StoredAgentRun,
    *,
    documents: tuple[DocumentReference, ...] | None = None,
) -> InvestigationTurnResponse:
    result = record.result
    return InvestigationTurnResponse(
        run_id=record.run_id,
        sequence=record.investigation_sequence,
        status=record.status,
        data_classification=DataClassificationLabel[record.data_classification.name],
        response_language=record.response_language.value,
        request=sanitize_public_text(record.request_text) or "",
        answer=sanitize_public_text(result.final_answer) if result else None,
        recovery_outcome=result.recovery_outcome if result else None,
        investigation_steps=_to_investigation_steps(result),
        next_steps=_to_next_steps(result),
        identifiers=_to_identifiers(result),
        documents=_to_documents(documents if documents is not None else result),
        tool_calls=_to_tool_calls(result),
        error=_to_persisted_run_error(record),
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
    store: AgentRunStore,
    run_id: UUID,
    execution: RunExecution,
    *,
    documents: tuple[DocumentReference, ...] = (),
) -> StoredAgentRun:
    if execution.result is not None:
        return await store.complete(
            run_id, _with_authorized_documents(execution.result, documents)
        )
    approval = execution.approval
    if approval is None:
        raise RuntimeError("Run execution was incomplete")
    record = await store.get(run_id)
    if record is None or record.model_profile is None:
        raise RuntimeError("Approval requires a bound execution context")
    approval_request: dict[str, object] = {
        "action": approval.action,
        "summary": approval.summary,
        "arguments": approval.arguments,
        "classification": record.data_classification.name,
        "model_profile": record.model_profile,
        "status": RunStatus.WAITING_FOR_APPROVAL.value,
        "created_at": datetime.now(UTC).isoformat(),
    }
    if approval.action_id is not None:
        approval_request["action_id"] = approval.action_id
    return await store.wait_for_approval(run_id, approval_request)


def _to_approval_request(
    payload: dict[str, object] | None,
) -> ApprovalRequestResponse | None:
    if payload is None:
        return None
    public_payload = {
        key: value for key, value in payload.items() if key != "action_id"
    }
    return ApprovalRequestResponse.model_validate(sanitize_public_value(public_payload))


def _to_persisted_run_error(record: StoredAgentRun) -> ApiErrorResponse | None:
    if record.status is not RunStatus.FAILED or record.error_code is None:
        return None
    code = (
        record.error_code
        if record.error_code in _PERSISTED_RUN_ERROR_CODES
        else "internal_error"
    )
    return ApiErrorResponse(
        code=code,
        message=user_facing_error_message(code, record.response_language),
    )


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


def _to_next_steps(result: AgentRunResult | None) -> tuple[str, ...]:
    if result is None:
        return ()
    return tuple(
        sanitized
        for step in result.next_steps
        if (sanitized := sanitize_public_text(step)) is not None
    )


def _to_identifiers(result: AgentRunResult | None):
    if result is None:
        return ()
    from industrial_ai_agent.infrastructure.api.schemas import (
        IdentifierReferenceResponse,
        IdentifierTypeResponse,
    )

    return tuple(
        IdentifierReferenceResponse(
            value=reference.value,
            type=IdentifierTypeResponse(reference.type.value),
        )
        for reference in result.identifiers
    )


def _to_documents(
    result_or_documents: AgentRunResult | tuple[DocumentReference, ...] | None,
):
    if result_or_documents is None:
        return ()
    from industrial_ai_agent.infrastructure.api.schemas import DocumentReferenceResponse

    return tuple(
        DocumentReferenceResponse(
            document_id=reference.document_id,
            title=sanitize_public_text(reference.title) or reference.document_id,
            format=reference.format,
        )
        for reference in (
            result_or_documents.documents
            if isinstance(result_or_documents, AgentRunResult)
            else result_or_documents
        )
    )


def _to_investigation_steps(
    result: AgentRunResult | None,
) -> tuple[InvestigationStepResponse, ...]:
    if result is None:
        return ()
    return tuple(
        InvestigationStepResponse(
            step=step.step,
            action=PublicToolName(step.action),
            finding=sanitize_public_text(step.finding) or "No finding recorded.",
        )
        for step in result.investigation_steps
    )


def _raise_api_run_error(
    *,
    status_code: int,
    code: str,
    message: str,
) -> NoReturn:
    raise _ApiRunError(status_code=status_code, code=code, message=message)
