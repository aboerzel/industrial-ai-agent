"""Generate synthetic, internally consistent FACTORY-DEMO-01 portfolio assets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from docx import Document
from openpyxl import Workbook
from openpyxl.styles import Font
from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Inches as SlideInches

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = PROJECT_ROOT / "demo_factory"
EFFECTIVE_DATE = "2026-01-17"
SOURCE_SYSTEM = "FACTORY-DEMO-01-DOCUMENTS"

DOCUMENTS = (
    (
        "public/Factory_Overview.pdf",
        "Factory Overview",
        "PUBLIC",
        "application/pdf",
        None,
        "FO-100",
    ),
    (
        "public/S04_Quality_Inspection_Overview.pptx",
        "S04 Quality Inspection Overview",
        "PUBLIC",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "S04",
        "QI-104",
    ),
    (
        "internal/Operator_Handbook.docx",
        "Operator Handbook",
        "INTERNAL",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "S02",
        "OH-210",
    ),
    (
        "internal/Station_Layout.xlsx",
        "Station Layout",
        "INTERNAL",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        None,
        "SL-211",
    ),
    (
        "confidential/Positioning_Error_Troubleshooting.pdf",
        "Positioning Error Troubleshooting",
        "CONFIDENTIAL",
        "application/pdf",
        "S02",
        "TS-320",
    ),
    (
        "confidential/Maintenance_Report_S02.docx",
        "Maintenance Report S02",
        "CONFIDENTIAL",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "S02",
        "MR-321",
    ),
    (
        "confidential/Failure_Analysis_S02.pptx",
        "Failure Analysis S02",
        "CONFIDENTIAL",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "S02",
        "FA-322",
    ),
    (
        "restricted/Process_Recipe.xlsx",
        "Process Recipe",
        "RESTRICTED",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "S03",
        "PR-430",
    ),
    (
        "restricted/Robot_Calibration_Parameters.xlsx",
        "Robot Calibration Parameters",
        "RESTRICTED",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "S03",
        "RC-431",
    ),
)
IMAGES = (
    (
        "images/S02_Positioning_Reference.png",
        "S02 Positioning Reference",
        "INTERNAL",
        "S02",
        "IMG-210",
    ),
    (
        "images/S04_Inspection_Good.png",
        "S04 Inspection Good Reference",
        "PUBLIC",
        "S04",
        "IMG-104",
    ),
    (
        "images/S04_Inspection_Defect.png",
        "S04 Inspection Defect Reference",
        "CONFIDENTIAL",
        "S04",
        "IMG-324",
    ),
)


def main() -> None:
    for relative_path, title, classification, _, station, document_id in DOCUMENTS:
        path = ASSET_ROOT / "documents" / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_document(path, title, classification, station, document_id)
    for relative_path, title, classification, station, document_id in IMAGES:
        path = ASSET_ROOT / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_image(path, title, classification, station, document_id)
    _write_catalog()


def _write_document(
    path: Path, title: str, classification: str, station: str | None, document_id: str
) -> None:
    if path.suffix == ".pdf":
        _write_pdf(path, title, classification, station, document_id)
    elif path.name == "Maintenance_Report_S02.docx":
        _write_maintenance_report(path, classification, document_id)
    elif path.name == "Operator_Handbook.docx":
        _write_operator_handbook(path, classification, document_id)
    elif path.name == "Failure_Analysis_S02.pptx":
        _write_failure_analysis(path, classification, document_id)
    elif path.name == "S04_Quality_Inspection_Overview.pptx":
        _write_quality_overview(path, classification, document_id)
    elif path.name == "Process_Recipe.xlsx":
        _write_process_recipe(path, classification, document_id)
    elif path.name == "Robot_Calibration_Parameters.xlsx":
        _write_calibration(path, classification, document_id)
    else:
        _write_station_layout(path, classification, document_id)


def _document_control(
    title: str, classification: str, station: str | None, document_id: str
) -> list[str]:
    return [
        f"Document ID: {document_id}",
        f"Title: {title}",
        "Factory: FACTORY-DEMO-01",
        f"Station: {station or 'All stations'}",
        f"Classification: {classification}",
        "Revision: 1.1",
        f"Effective Date: {EFFECTIVE_DATE}",
        "Owner: Demo Operations Engineering",
        "Status: Approved",
        "Synthetic demonstration document",
    ]


def _write_pdf(
    path: Path, title: str, classification: str, station: str | None, document_id: str
) -> None:
    if path.name == "Factory_Overview.pdf":
        pages = [
            [
                *_document_control(title, classification, station, document_id),
                "",
                "Purpose",
                "FACTORY-DEMO-01 is a synthetic automated assembly and inspection line.",
                "",
                "High-level process flow",
                "S01 Material Intake -> S02 Positioning -> S03 Robot Assembly -> S04 Quality Inspection -> S05 Packaging",
                "",
                "Capabilities",
                "Traceable assembly, high-level quality decisions, and controlled material flow.",
                "",
                "Revision History",
                "1.1 | 2026-01-17 | Demo Operations Engineering | Portfolio refresh",
            ]
        ]
    else:
        pages = [
            [
                *_document_control(title, classification, station, document_id),
                "",
                "Purpose and Scope",
                "This procedure addresses POSITION-ENC-02 on station S02 Positioning.",
                "Applies to P4711 investigations and repeated P4801/P4802/P4805/P4811 position warnings.",
                "",
                "Observable symptoms",
                "Positioning warning, failed homing reference, cycle interruption, downstream QUALITY-09 rejection.",
            ],
            [
                "TS-320 | S02 diagnostic workflow | Page 2 of 5",
                "",
                "Prerequisites and safety notes",
                "Place S02 in maintenance mode. Follow local lockout and safety-zone procedures.",
                "",
                "Numbered procedure",
                "1. Record active alarms and product context.",
                "2. Inspect encoder connector, cable routing, and reference mark.",
                "3. Compare measured position against commanded reference.",
                "4. Execute controlled homing and record result.",
            ],
            [
                "TS-320 | S02 positioning and verification | Page 3 of 5",
                "",
                "Encoder and positioning checks",
                "Verify encoder feedback stability and mechanical coupling. Do not change restricted robot parameters.",
                "",
                "Homing and dry cycle",
                "Run homing after approved component replacement. Complete three dry cycles without POSITION-ENC-02.",
                "",
                "Related events",
                "P4711: S02 warning then S04 QUALITY-09 rejection. S02 alarm history includes E-STOP-17 escalation.",
            ],
            [
                "TS-320 | S02 return to service | Page 4 of 5",
                "",
                "Verification and return-to-service criteria",
                "Inspection verification passes, dry cycle is stable, and no active S02 position alarm remains.",
                "",
                "Escalation criteria",
                "Escalate if feedback remains unstable after encoder replacement or if repeated products fail the same position check.",
                "",
                "Revision history",
                "1.1 | 2026-01-17 | Added repeated S02 failure context | Demo Operations Engineering",
            ],
        ]
    _write_simple_pdf(path, pages)


def _write_simple_pdf(path: Path, pages: list[list[str]]) -> None:
    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    page_refs = " ".join(f"{index} 0 R" for index in range(3, 3 + len(pages)))
    objects.append(
        f"<< /Type /Pages /Kids [{page_refs}] /Count {len(pages)} >>".encode()
    )
    font_index = 3 + len(pages)
    content_start = font_index + 1
    for index in range(len(pages)):
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {font_index} 0 R >> >> /Contents {content_start + index} 0 R >>".encode()
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for page in pages:
        lines = []
        y = 740
        for line in page:
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            lines.append(f"BT /F1 10 Tf 54 {y} Td ({escaped}) Tj ET")
            y -= 18
        stream = "\n".join(lines).encode("latin-1", "replace")
        objects.append(
            b"<< /Length "
            + str(len(stream)).encode()
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, value in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode())
        output.extend(value)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    path.write_bytes(output)


def _write_doc_header(
    document: Document,
    title: str,
    classification: str,
    document_id: str,
    station: str | None,
) -> None:
    document.add_heading(title, 0)
    document.add_paragraph(
        " | ".join(_document_control(title, classification, station, document_id)[:8])
    )


def _write_maintenance_report(
    path: Path, classification: str, document_id: str
) -> None:
    d = Document()
    _write_doc_header(d, "Maintenance Report S02", classification, document_id, "S02")
    for heading, body in (
        (
            "Work Order",
            "MT-S02-20260117 | Technician: Demo Technician A. Novak | Downtime: 42 minutes",
        ),
        (
            "Trigger and initial diagnosis",
            "Repeated POSITION-ENC-02 warnings on P4801, P4802, P4805 and P4811. Encoder feedback was unstable during homing.",
        ),
        (
            "Findings",
            "Connector seating was acceptable; encoder signal drift exceeded the demo maintenance tolerance.",
        ),
        (
            "Corrective work",
            "Encoder replacement, controlled homing, three dry cycles, and S04 inspection verification completed.",
        ),
        (
            "Measurements",
            "Before: reference deviation 0.84 mm. After: reference deviation 0.06 mm.",
        ),
        (
            "Return to service",
            "S02 returned to service after dry-cycle and inspection verification. Final status: CLOSED.",
        ),
        (
            "Sign-off",
            "Demo Technician A. Novak | Demo Operations Engineering | Revision 1.1",
        ),
    ):
        d.add_heading(heading, 1)
        d.add_paragraph(body)
    d.save(path)


def _write_operator_handbook(path: Path, classification: str, document_id: str) -> None:
    d = Document()
    _write_doc_header(d, "Operator Handbook", classification, document_id, "S01-S05")
    for heading, body in (
        (
            "Factory overview",
            "S01 Material Intake, S02 Positioning, S03 Robot Assembly, S04 Quality Inspection, S05 Packaging.",
        ),
        (
            "Normal operation",
            "Confirm line-ready state, follow HMI prompts, and preserve product traceability.",
        ),
        (
            "Startup and shutdown",
            "Use approved line procedures. Do not bypass safety zones or maintenance interlocks.",
        ),
        (
            "Alarm handling",
            "Record alarm code, station, product and time. Escalate E-STOP-17 or repeated POSITION-ENC-02 to maintenance.",
        ),
        (
            "Quality workflow",
            "S04 produces accepted or rejected outcomes. QUALITY-09 requires a documented engineering review.",
        ),
        (
            "Responsibilities",
            "Operators protect safe operation and escalate; they do not change restricted recipes or calibration offsets.",
        ),
    ):
        d.add_heading(heading, 1)
        d.add_paragraph(body)
    d.save(path)


def _presentation(title: str, classification: str, document_id: str) -> Presentation:
    p = Presentation()
    p.slide_width = SlideInches(13.333)
    p.slide_height = SlideInches(7.5)
    slide = p.slides.add_slide(p.slide_layouts[0])
    slide.shapes.title.text = title
    slide.placeholders[
        1
    ].text = f"{document_id} | FACTORY-DEMO-01 | Classification: {classification} | Revision 1.1"
    return p


def _add_slide(p: Presentation, title: str, lines: list[str]) -> None:
    slide = p.slides.add_slide(p.slide_layouts[1])
    slide.shapes.title.text = title
    slide.placeholders[1].text = "\n".join(lines)


def _add_failure_trend_chart_slide(p: Presentation) -> None:
    """Visualize the repeated S02 warnings from the deterministic demo timeline."""
    slide = p.slides.add_slide(p.slide_layouts[5])
    slide.shapes.title.text = "Failure Trend"
    chart_data = CategoryChartData()
    chart_data.categories = ("08:00", "08:11", "08:22", "08:33")
    chart_data.add_series("S02 positioning warnings", (1, 1, 1, 1))
    chart = slide.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED,
        SlideInches(1.0),
        SlideInches(1.5),
        SlideInches(8.0),
        SlideInches(4.5),
        chart_data,
    ).chart
    chart.has_legend = False
    chart.value_axis.maximum_scale = 2
    chart.value_axis.minimum_scale = 0
    text_box = slide.shapes.add_textbox(
        SlideInches(9.3), SlideInches(1.9), SlideInches(3.0), SlideInches(2.5)
    )
    text_box.text_frame.text = (
        "Four warnings in 33 minutes\n\n"
        "Pattern indicates a station condition, not isolated product variation."
    )


def _write_failure_analysis(path: Path, classification: str, document_id: str) -> None:
    p = _presentation("Failure Analysis S02", classification, document_id)
    _add_slide(
        p,
        "Incident Summary",
        [
            "Repeated S02 positioning warnings",
            "Affected products: P4801, P4802, P4805, P4811",
            "Related code: POSITION-ENC-02",
        ],
    )
    _add_failure_trend_chart_slide(p)
    _add_slide(
        p,
        "Affected Products",
        ["P4801 | 08:00", "P4802 | 08:11", "P4805 | 08:22", "P4811 | 08:33"],
    )
    _add_slide(
        p,
        "Event Timeline",
        [
            "08:35 E-STOP-17 escalation",
            "09:01 encoder replacement",
            "09:02 homing",
            "09:03 dry cycle",
            "09:04 inspection verification",
            "09:05 return to service",
        ],
    )
    _add_slide(
        p,
        "Root Cause Analysis",
        [
            "Encoder feedback drift caused unstable positioning reference",
            "No restricted process recipe change was required",
        ],
    )
    _add_slide(
        p,
        "Corrective Actions",
        [
            "Replace encoder",
            "Home station",
            "Perform dry cycle",
            "Verify inspection",
            "Return to service with closed work order",
        ],
    )
    _add_slide(
        p,
        "Verification and Conclusion",
        [
            "Reference deviation reduced from 0.84 mm to 0.06 mm",
            "No repeat POSITION-ENC-02 after verification",
        ],
    )
    p.save(path)


def _write_quality_overview(path: Path, classification: str, document_id: str) -> None:
    p = _presentation("S04 Quality Inspection Overview", classification, document_id)
    _add_slide(
        p, "Purpose", ["High-level quality decision overview for FACTORY-DEMO-01."]
    )
    _add_slide(
        p,
        "Inspection Concept",
        [
            "S04 evaluates assembled product condition against approved inspection logic."
        ],
    )
    _add_slide(
        p,
        "Quality Flow",
        ["Receive product -> inspect -> accept or reject -> record outcome."],
    )
    _add_slide(
        p,
        "Decision Outcomes",
        [
            "Accepted products continue to S05 Packaging.",
            "Rejected products are routed for controlled review.",
        ],
    )
    p.save(path)


def _write_workbook_metadata(
    wb: Workbook, title: str, classification: str, document_id: str
) -> None:
    sheet = wb.active
    sheet.title = "Metadata"
    sheet.append(["Document ID", document_id])
    sheet.append(["Title", title])
    sheet.append(["Factory", "FACTORY-DEMO-01"])
    sheet.append(["Classification", classification])
    sheet.append(["Revision", "1.1"])
    sheet.append(["Effective Date", EFFECTIVE_DATE])
    sheet.append(["Owner", "Demo Operations Engineering"])
    sheet.append(["Status", "Approved"])
    for row in sheet.iter_rows():
        row[0].font = Font(bold=True)


def _write_process_recipe(path: Path, classification: str, document_id: str) -> None:
    wb = Workbook()
    _write_workbook_metadata(wb, "Process Recipe", classification, document_id)
    params = wb.create_sheet("Process Parameters")
    params.append(
        [
            "parameter_id",
            "station",
            "parameter_name",
            "nominal_value",
            "lower_limit",
            "upper_limit",
            "unit",
            "revision",
            "classification",
        ]
    )
    params.append(
        [
            "PP-S03-001",
            "S03",
            "robot_trajectory_limit",
            "12.5",
            "11.5",
            "13.5",
            "mm/s",
            "1.1",
            "RESTRICTED",
        ]
    )
    params.append(
        [
            "PP-S03-002",
            "S03",
            "assembly_force_reference",
            "320",
            "300",
            "340",
            "N",
            "1.1",
            "RESTRICTED",
        ]
    )
    limits = wb.create_sheet("Limits")
    limits.append(["station", "limit_name", "status", "classification"])
    limits.append(["S03", "Trajectory envelope", "Controlled", "RESTRICTED"])
    mapping = wb.create_sheet("Product Mapping")
    mapping.append(["product", "recipe_revision", "classification"])
    mapping.append(["P4711", "1.1", "RESTRICTED"])
    history = wb.create_sheet("Revision History")
    history.append(["revision", "date", "change", "owner"])
    history.append(
        [
            "1.1",
            EFFECTIVE_DATE,
            "Synthetic demo recipe baseline",
            "Demo Process Engineering",
        ]
    )
    wb.save(path)


def _write_calibration(path: Path, classification: str, document_id: str) -> None:
    wb = Workbook()
    _write_workbook_metadata(
        wb, "Robot Calibration Parameters", classification, document_id
    )
    params = wb.create_sheet("Calibration Parameters")
    params.append(
        [
            "robot_id",
            "axis",
            "offset",
            "unit",
            "valid_from",
            "calibration_method",
            "tolerance",
            "status",
            "classification",
        ]
    )
    for axis, offset in (("A1", "0.04"), ("A2", "-0.03"), ("A3", "0.02")):
        params.append(
            [
                "RB-S03-01",
                axis,
                offset,
                "mm",
                EFFECTIVE_DATE,
                "Reference fixture",
                "0.10 mm",
                "VALID",
                "RESTRICTED",
            ]
        )
    history = wb.create_sheet("Revision History")
    history.append(["revision", "date", "change", "owner"])
    history.append(
        [
            "1.1",
            EFFECTIVE_DATE,
            "Synthetic calibration baseline",
            "Demo Automation Engineering",
        ]
    )
    wb.save(path)


def _write_station_layout(path: Path, classification: str, document_id: str) -> None:
    wb = Workbook()
    _write_workbook_metadata(wb, "Station Layout", classification, document_id)
    stations = wb.create_sheet("Stations")
    stations.append(
        [
            "station_id",
            "station_type",
            "upstream",
            "downstream",
            "primary_equipment",
            "safety_zone",
            "nominal_cycle_time_s",
            "owner",
        ]
    )
    rows = [
        (
            "S01",
            "Material Intake",
            "-",
            "S02",
            "Feeder",
            "SZ-01",
            24,
            "Material Operations",
        ),
        (
            "S02",
            "Positioning",
            "S01",
            "S03",
            "Positioning fixture",
            "SZ-02",
            31,
            "Assembly Operations",
        ),
        (
            "S03",
            "Robot Assembly",
            "S02",
            "S04",
            "Demo robot",
            "SZ-03",
            42,
            "Automation Engineering",
        ),
        (
            "S04",
            "Quality Inspection",
            "S03",
            "S05",
            "Inspection frame",
            "SZ-04",
            28,
            "Quality Operations",
        ),
        (
            "S05",
            "Packaging",
            "S04",
            "-",
            "Packing cell",
            "SZ-05",
            20,
            "Packaging Operations",
        ),
    ]
    for row in rows:
        stations.append(row)
    wb.save(path)


def _write_image(
    path: Path, title: str, classification: str, station: str, document_id: str
) -> None:
    image = Image.new("RGB", (1200, 700), "#e7edf0")
    draw = ImageDraw.Draw(image)
    draw.rectangle((35, 35, 1165, 665), outline="#163f59", width=6)
    draw.rectangle((65, 95, 1135, 600), fill="#ccd9df", outline="#163f59", width=3)
    draw.text(
        (80, 55),
        f"{document_id} | FACTORY-DEMO-01 | {station} | {classification}",
        fill="#163f59",
    )
    if "Positioning" in title:
        draw.rectangle((310, 250, 880, 410), fill="#78909c", outline="#263238", width=5)
        draw.ellipse((535, 265, 665, 395), fill="#90a4ae", outline="#263238", width=4)
        draw.line((150, 330, 1020, 330), fill="#f6b93b", width=6)
        label = "POSITIONING REFERENCE"
    else:
        draw.rectangle((350, 180, 850, 540), fill="#ffffff", outline="#263238", width=5)
        color = "#2e7d32" if "Good" in title else "#c62828"
        draw.ellipse((520, 260, 680, 420), fill=color)
        label = "ACCEPTED FRAME" if "Good" in title else "QUALITY-09 DEFECT FRAME"
    draw.text((400, 620), label, fill="#17211f")
    image.save(path, format="PNG")


def _write_catalog() -> None:
    metadata = []
    for (
        relative_path,
        title,
        classification,
        mime_type,
        station,
        document_id,
    ) in DOCUMENTS:
        path = ASSET_ROOT / "documents" / relative_path
        metadata.append(
            _catalog_entry(
                f"documents/{relative_path}",
                path,
                title,
                classification,
                mime_type,
                station,
                document_id,
            )
        )
    for relative_path, title, classification, station, document_id in IMAGES:
        path = ASSET_ROOT / relative_path
        metadata.append(
            _catalog_entry(
                relative_path,
                path,
                title,
                classification,
                "image/png",
                station,
                document_id,
            )
        )
    target = ASSET_ROOT / "metadata" / "document_catalog.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def _catalog_entry(
    relative_path: str,
    path: Path,
    title: str,
    classification: str,
    mime_type: str,
    station: str | None,
    document_id: str,
) -> dict[str, object]:
    return {
        "document_id": "doc-" + hashlib.sha256(relative_path.encode()).hexdigest()[:16],
        "title": title,
        "classification": classification,
        "mime_type": mime_type,
        "source_system": SOURCE_SYSTEM,
        "factory_code": "FACTORY-DEMO-01",
        "station_code": station,
        "version": "1.1",
        "valid_from": EFFECTIVE_DATE,
        "tags": [
            document_id,
            "FACTORY-DEMO-01",
            *(
                item
                for item in (
                    station,
                    "POSITION-ENC-02" if station == "S02" else None,
                    "QUALITY-09" if station == "S04" else None,
                )
                if item
            ),
        ],
        "file_path": relative_path,
        "checksum": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


if __name__ == "__main__":
    main()
