"""Server-side PDF projection for already-authorized investigation history."""

import re
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

import reportlab
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from industrial_ai_agent.infrastructure.api.schemas import InvestigationResponse

_PDF_FONT_FAMILY = "IndustrialPdfVera"


def _register_pdf_fonts() -> tuple[str, str]:
    """Use ReportLab's bundled Unicode fonts instead of lossy Type-1 encodings."""
    if _PDF_FONT_FAMILY not in pdfmetrics.getRegisteredFontNames():
        font_directory = Path(reportlab.__file__).resolve().parent / "fonts"
        pdfmetrics.registerFont(TTFont(_PDF_FONT_FAMILY, font_directory / "Vera.ttf"))
        pdfmetrics.registerFont(
            TTFont(f"{_PDF_FONT_FAMILY}-Bold", font_directory / "VeraBd.ttf")
        )
        pdfmetrics.registerFont(
            TTFont(f"{_PDF_FONT_FAMILY}-Italic", font_directory / "VeraIt.ttf")
        )
        pdfmetrics.registerFont(
            TTFont(f"{_PDF_FONT_FAMILY}-BoldItalic", font_directory / "VeraBI.ttf")
        )
        pdfmetrics.registerFontFamily(
            _PDF_FONT_FAMILY,
            normal=_PDF_FONT_FAMILY,
            bold=f"{_PDF_FONT_FAMILY}-Bold",
            italic=f"{_PDF_FONT_FAMILY}-Italic",
            boldItalic=f"{_PDF_FONT_FAMILY}-BoldItalic",
        )
    return _PDF_FONT_FAMILY, _PDF_FONT_FAMILY


def render_investigation_pdf(investigation: InvestigationResponse) -> bytes:
    """Render only the public history projection supplied by the API route."""
    body_font, code_font = _register_pdf_fonts()
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
    for style in styles.byName.values():
        style.fontName = body_font
    styles["Code"].fontName = code_font
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
                *_markdown_flowables(turn.request, styles, code_font),
                Paragraph("Agent", label),
                *_markdown_flowables(
                    turn.answer or "No final answer recorded.", styles, code_font
                ),
            ]
        )
        if turn.investigation_steps:
            summary_label = (
                "Untersuchungsübersicht"
                if turn.response_language == "DE"
                else "Investigation Summary"
            )
            headings = (
                ("Schritt", "Aktion", "Erkenntnisse / Hinweise")
                if turn.response_language == "DE"
                else ("Step", "Action", "Findings / Notes")
            )
            rows = [
                [Paragraph(escape(value), text) for value in headings],
                *[
                    [
                        Paragraph(str(step.step), text),
                        Paragraph(escape(step.action.value), text),
                        Paragraph(_inline_markup(step.finding, code_font), text),
                    ]
                    for step in turn.investigation_steps
                ],
            ]
            table = Table(rows, colWidths=(16 * mm, 43 * mm, 109 * mm), repeatRows=1)
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#edf3f0")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#1d332a")),
                        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cbd6d1")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ]
                )
            )
            story.extend([Paragraph(summary_label, label), table, Spacer(1, 2 * mm)])
        if turn.next_steps:
            next_steps_label = (
                "Empfohlene Untersuchungsschritte"
                if turn.response_language == "DE"
                else "Recommended Investigation Actions"
            )
            story.append(Paragraph(next_steps_label, label))
            story.extend(
                Paragraph(_inline_markup(step, code_font), text, bulletText="•")
                for step in turn.next_steps
            )
        if turn.identifiers or turn.documents:
            references_label = (
                "Referenzen" if turn.response_language == "DE" else "References"
            )
            story.append(Paragraph(references_label, label))
            story.extend(
                Paragraph(
                    _inline_markup(reference.value, code_font), text, bulletText="•"
                )
                for reference in turn.identifiers
            )
            story.extend(
                Paragraph(
                    _inline_markup(
                        f"{reference.title} ({reference.document_id})", code_font
                    ),
                    text,
                    bulletText="•",
                )
                for reference in turn.documents
            )
        if turn.tool_calls:
            names = "<br/>".join(escape(call.tool) for call in turn.tool_calls)
            story.extend([Paragraph("Executed tools", label), Paragraph(names, text)])
        if turn.error is not None:
            error_label = "Fehler" if turn.response_language == "DE" else "Error"
            story.extend(
                [
                    Paragraph(error_label, label),
                    Paragraph(escape(turn.error.code), text),
                    Paragraph(_inline_markup(turn.error.message, code_font), text),
                ]
            )
        if turn.recovery_outcome is not None:
            recovery_label = (
                "Recovery-Ergebnis"
                if turn.response_language == "DE"
                else "Recovery outcome"
            )
            recovery_text = (
                "Keine Aktion war erforderlich."
                if turn.recovery_outcome.value == "NOT_REQUIRED"
                and turn.response_language == "DE"
                else "No action was required."
                if turn.recovery_outcome.value == "NOT_REQUIRED"
                else "Die Recovery wurde ausgeführt und unabhängig verifiziert."
                if turn.recovery_outcome.value == "SUCCEEDED"
                and turn.response_language == "DE"
                else "Recovery was executed and verified."
                if turn.recovery_outcome.value == "SUCCEEDED"
                else "Die Recovery wurde blockiert, bevor eine Aktion ausgeführt wurde."
                if turn.recovery_outcome.value == "BLOCKED"
                and turn.response_language == "DE"
                else "Recovery was blocked before an action was executed."
                if turn.recovery_outcome.value == "BLOCKED"
                else "Die Recovery ergab keine verifizierte Wiederherstellung."
                if turn.recovery_outcome.value == "FAILED"
                and turn.response_language == "DE"
                else "Recovery did not produce a verified restoration."
                if turn.recovery_outcome.value == "FAILED"
                else turn.recovery_outcome.value
            )
            story.extend(
                [Paragraph(recovery_label, label), Paragraph(recovery_text, text)]
            )
        story.extend(
            [
                Paragraph("Status", label),
                Paragraph(escape(turn.status.value), text),
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


_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$")
_UNORDERED_LIST_PATTERN = re.compile(r"^\s*[-*+]\s+(.+)$")
_ORDERED_LIST_PATTERN = re.compile(r"^\s*(\d+)\.\s+(.+)$")


def _markdown_flowables(
    value: str, styles: dict[str, ParagraphStyle], code_font: str
) -> list[object]:
    """Render the supported Markdown subset without admitting model-provided HTML."""
    story: list[object] = []
    lines = value.splitlines() or [""]
    index = 0
    body = ParagraphStyle("PdfNarrative", parent=styles["BodyText"], leading=15)
    code = ParagraphStyle(
        "PdfCode", parent=styles["Code"], leftIndent=8, rightIndent=8, leading=11
    )
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if line.startswith("```"):
            index += 1
            code_lines: list[str] = []
            while index < len(lines) and not lines[index].startswith("```"):
                code_lines.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            story.append(Preformatted(escape("\n".join(code_lines)), code))
            story.append(Spacer(1, 2 * mm))
            continue
        heading = _HEADING_PATTERN.match(line)
        if heading:
            depth = min(len(heading.group(1)) + 1, 4)
            story.append(
                Paragraph(
                    _inline_markup(heading.group(2), code_font),
                    styles[f"Heading{depth}"],
                )
            )
            index += 1
            continue
        if _is_markdown_table(lines, index):
            table_lines: list[str] = []
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                table_lines.append(lines[index])
                index += 1
            story.append(_markdown_table(table_lines, body, code_font))
            story.append(Spacer(1, 2 * mm))
            continue
        unordered = _UNORDERED_LIST_PATTERN.match(line)
        ordered = _ORDERED_LIST_PATTERN.match(line)
        if unordered or ordered:
            while index < len(lines):
                item = _UNORDERED_LIST_PATTERN.match(
                    lines[index]
                ) or _ORDERED_LIST_PATTERN.match(lines[index])
                if not item:
                    break
                text_value = item.group(item.lastindex or 1)
                bullet = (
                    "•" if item.re is _UNORDERED_LIST_PATTERN else f"{item.group(1)}."
                )
                story.append(
                    Paragraph(
                        _inline_markup(text_value, code_font), body, bulletText=bullet
                    )
                )
                index += 1
            continue
        paragraph_lines: list[str] = []
        while index < len(lines) and lines[index].strip():
            if (
                lines[index].startswith("```")
                or _HEADING_PATTERN.match(lines[index])
                or _UNORDERED_LIST_PATTERN.match(lines[index])
                or _ORDERED_LIST_PATTERN.match(lines[index])
                or _is_markdown_table(lines, index)
            ):
                break
            paragraph_lines.append(lines[index])
            index += 1
        if paragraph_lines:
            story.append(
                Paragraph(
                    "<br/>".join(
                        _inline_markup(item, code_font) for item in paragraph_lines
                    ),
                    body,
                )
            )
        else:
            index += 1
    return story


def _is_markdown_table(lines: list[str], index: int) -> bool:
    return (
        index + 1 < len(lines)
        and "|" in lines[index]
        and bool(re.match(r"^\s*\|?\s*:?-{3,}", lines[index + 1]))
    )


def _markdown_table(lines: list[str], style: ParagraphStyle, code_font: str) -> Table:
    rows = [_split_table_row(line) for line in lines if not _is_table_separator(line)]
    table = Table(
        [
            [Paragraph(_inline_markup(cell, code_font), style) for cell in row]
            for row in rows
        ],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), HexColor("#edf3f0")),
                ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cbd6d1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _is_table_separator(line: str) -> bool:
    return bool(re.match(r"^\s*\|?\s*:?-{3,}", line))


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _inline_markup(value: str, code_font: str = _PDF_FONT_FAMILY) -> str:
    escaped = escape(value)
    # The enclosing Unicode font preserves technical characters; inline code remains
    # semantically separated from Markdown without switching back to a Type-1 font.
    escaped = re.sub(r"`([^`]+)`", r"\1", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*|__([^_]+)__", r"<b>\1\2</b>", escaped)
    return re.sub(
        r"(?<!\*)\*([^*]+)\*(?!\*)|(?<!_)_([^_]+)_(?!_)", r"<i>\1\2</i>", escaped
    )
