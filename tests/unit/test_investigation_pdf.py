from uuid import UUID

from industrial_ai_agent.infrastructure.api.investigation_pdf import (
    render_investigation_pdf,
)
from industrial_ai_agent.infrastructure.api.schemas import (
    ApiErrorResponse,
    DocumentReferenceResponse,
    IdentifierReferenceResponse,
    InvestigationResponse,
    InvestigationTurnResponse,
    RunStatus,
    ToolCallResponse,
)

INVESTIGATION_ID = UUID("123e4567-e89b-42d3-a456-426614174000")


def test_pdf_export_preserves_success_turn_data_and_excludes_internal_payloads() -> (
    None
):
    pdf = _pdf_text(
        _investigation(
            _turn(
                sequence=1,
                status=RunStatus.SUCCESS,
                response_language="DE",
                identifiers=(
                    IdentifierReferenceResponse(value="S04", type="station"),
                    IdentifierReferenceResponse(value="P4101", type="product"),
                    IdentifierReferenceResponse(value="QUALITY-09", type="error_code"),
                ),
                documents=(
                    DocumentReferenceResponse(
                        document_id="doc-quality-09",
                        title="S04 QUALITY-09 Procedure",
                        format="markdown",
                    ),
                ),
                tool_calls=(
                    ToolCallResponse(
                        tool="get_machine_status", arguments={"station_id": "S04"}
                    ),
                ),
            )
        )
    )

    assert pdf.startswith(b"%PDF-")
    assert b"Untersuchungsbericht" in pdf
    assert str(INVESTIGATION_ID).encode() in pdf
    assert b"SUCCESS" in pdf
    assert b"CONFIDENTIAL" in pdf
    assert b"S04" in pdf and b"P4101" in pdf and b"QUALITY-09" in pdf
    assert b"S04 QUALITY-09 Procedure" in pdf
    assert b"doc-quality-09" in pdf
    assert b"get_machine_status" in pdf
    assert b"station_id" not in pdf
    assert b"No final answer recorded" not in pdf


def test_pdf_export_keeps_attention_and_later_success_turn_local() -> None:
    pdf = _pdf_text(
        _investigation(
            _turn(
                sequence=1,
                status=RunStatus.FAILED,
                response_language="EN",
                error=ApiErrorResponse(
                    code="llm_rate_limit",
                    message="The language model is temporarily unavailable.",
                ),
            ),
            _turn(sequence=2, status=RunStatus.SUCCESS, response_language="EN"),
        )
    )

    first = pdf.index(b"Turn 1")
    second = pdf.index(b"Turn 2")
    assert b"ATTENTION" in pdf[first:second]
    assert b"SUCCESS" in pdf[second:]
    assert pdf.count(b"Turn 1") == pdf.count(b"Turn 2") == 1


def test_pdf_export_uses_english_chrome_and_sanitizes_failure_details() -> None:
    pdf = _pdf_text(
        _investigation(
            _turn(
                sequence=1,
                status=RunStatus.FAILED,
                response_language="EN",
                error=ApiErrorResponse(
                    code="agent_execution_timeout",
                    message=(
                        "The agent run could not be completed.\n"
                        "Traceback (most recent call last):\nsecret=secret-token"
                    ),
                ),
            )
        )
    )

    assert b"Investigation Report" in pdf
    assert b"Investigation ID" in pdf
    assert b"FAILURE" in pdf
    assert b"agent_execution_timeout" in pdf
    assert b"non-public diagnostic data" in pdf
    assert b"Traceback" not in pdf
    assert b"secret-token" not in pdf


def _investigation(*turns: InvestigationTurnResponse) -> InvestigationResponse:
    return InvestigationResponse(
        investigation_id=INVESTIGATION_ID,
        created_at="2026-09-21T12:00:00Z",
        run_count=len(turns),
        tool_call_count=sum(len(turn.tool_calls) for turn in turns),
        status=turns[-1].status.value,
        turns=turns,
    )


def _turn(
    *,
    sequence: int,
    status: RunStatus,
    response_language: str,
    identifiers: tuple[IdentifierReferenceResponse, ...] = (),
    documents: tuple[DocumentReferenceResponse, ...] = (),
    tool_calls: tuple[ToolCallResponse, ...] = (),
    error: ApiErrorResponse | None = None,
) -> InvestigationTurnResponse:
    return InvestigationTurnResponse(
        run_id=UUID(f"123e4567-e89b-42d3-a456-4266141740{sequence:02d}"),
        sequence=sequence,
        status=status,
        data_classification="CONFIDENTIAL",
        response_language=response_language,
        request=f"Request {sequence}",
        answer="Recorded answer" if status is RunStatus.SUCCESS else None,
        identifiers=identifiers,
        documents=documents,
        tool_calls=tool_calls,
        error=error,
        created_at="2026-09-21T12:00:00Z",
    )


def _pdf_text(investigation: InvestigationResponse) -> bytes:
    return render_investigation_pdf(investigation)
