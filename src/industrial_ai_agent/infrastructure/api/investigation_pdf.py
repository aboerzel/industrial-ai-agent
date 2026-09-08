"""Server-side PDF projection for already-authorized investigation history."""

from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

from industrial_ai_agent.infrastructure.api.schemas import InvestigationResponse


def render_investigation_pdf(investigation: InvestigationResponse) -> bytes:
    """Render only the public history projection supplied by the API route."""
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        pageCompression=0,
        title="Industrial AI Agent Investigation Report",
        author="Industrial AI Agent",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "InvestigationTitle", parent=styles["Title"], textColor=HexColor("#176b4b")
    )
    heading = ParagraphStyle(
        "TurnHeading", parent=styles["Heading2"], spaceBefore=10, spaceAfter=5
    )
    label = ParagraphStyle(
        "FieldLabel", parent=styles["Heading4"], spaceBefore=6, spaceAfter=3
    )
    text = ParagraphStyle("ReportText", parent=styles["BodyText"], leading=15)
    story = [
        Paragraph("Industrial AI Agent", styles["Heading3"]),
        Paragraph("Investigation Report", title),
        Spacer(1, 4 * mm),
        Paragraph(f"Investigation ID: {investigation.investigation_id}", text),
        Paragraph(f"Created: {investigation.created_at or 'Not recorded'}", text),
        Paragraph(f"Status: {investigation.status}", text),
        HRFlowable(
            width="100%", color=HexColor("#cbd6d1"), spaceBefore=5, spaceAfter=6
        ),
    ]
    for turn in investigation.turns:
        story.extend(
            [
                Paragraph(f"Turn {turn.sequence}", heading),
                Paragraph("User", label),
                Paragraph(_to_pdf_markup(turn.request), text),
                Paragraph("Agent", label),
                Paragraph(
                    _to_pdf_markup(turn.answer or "No final answer recorded."), text
                ),
            ]
        )
        if turn.tool_calls:
            names = "<br/>".join(escape(call.tool) for call in turn.tool_calls)
            story.extend([Paragraph("Executed tools", label), Paragraph(names, text)])
        story.extend(
            [
                Paragraph("Classification", label),
                Paragraph(escape(turn.data_classification.value), text),
                Paragraph(f"Created: {turn.created_at or 'Not recorded'}", text),
                HRFlowable(
                    width="100%", color=HexColor("#dde5e1"), spaceBefore=6, spaceAfter=4
                ),
            ]
        )
    story.extend(
        [
            Paragraph("Summary", heading),
            Paragraph(f"Runs: {investigation.run_count}", text),
            Paragraph(f"Tools: {investigation.tool_call_count}", text),
            Paragraph(f"Status: {investigation.status}", text),
        ]
    )
    document.build(story)
    return buffer.getvalue()


def _to_pdf_markup(value: str) -> str:
    """Keep technical content readable without interpreting Markdown or HTML."""
    return escape(value).replace("\n", "<br/>")
