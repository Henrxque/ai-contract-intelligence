import csv
import json
import re
from io import BytesIO, StringIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from app.errors import AnalysisError
from app.models import AnalysisResult


HEADERS = ["Field", "Value", "Status", "Required", "Issues", "Source pages", "Evidence"]


def safe_cell(value: str) -> str:
    # Prevent spreadsheet formula injection, including whitespace-prefixed formulas.
    return (
        "'" + value
        if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n"))
        else value
    )


def excel_cell(value: str) -> str:
    value = safe_cell(value)
    if len(value) > 32767:
        raise AnalysisError(
            "excel_cell_too_long",
            "A value exceeds Excel's cell length limit. Export JSON or CSV to preserve the full text.",
        )
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", value):
        raise AnalysisError(
            "excel_unsupported_text",
            "The extracted text contains a control character Excel cannot represent. Export JSON or CSV instead.",
        )
    return value


def field_rows(result: AnalysisResult) -> list[list[str]]:
    return [
        [
            field.label,
            field.value or "",
            field.status,
            "yes" if field.required else "no",
            " | ".join(field.issues),
            ", ".join(str(e.page) for e in field.evidence),
            " | ".join(e.quote for e in field.evidence),
        ]
        for field in result.fields
    ]


def metadata(result: AnalysisResult) -> list[list[str]]:
    return [
        ["Filename", result.filename],
        ["Document SHA-256", result.document_id],
        ["Mode", result.mode],
        ["Model", result.provider_model or "none"],
        ["Synthetic sample", str(result.sample)],
        ["Analyzed at", result.analyzed_at],
        ["Result", result.status],
        [
            "Input tokens",
            str(result.token_usage.input_tokens) if result.token_usage else "not reported",
        ],
        [
            "Output tokens",
            str(result.token_usage.output_tokens) if result.token_usage else "not reported",
        ],
        [
            "Cached input tokens",
            str(result.token_usage.cached_input_tokens) if result.token_usage else "not reported",
        ],
        ["Provider cost", "not measured"],
        ["Validation scope", "Format and source-evidence checks only; not legal review."],
        ["Notices", " | ".join(result.notices)],
    ]


def export_json(result: AnalysisResult) -> bytes:
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2).encode("utf-8")


def export_csv(result: AnalysisResult) -> bytes:
    stream = StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(HEADERS)
    writer.writerows([[safe_cell(cell) for cell in row] for row in field_rows(result)])
    writer.writerow([])
    writer.writerow(["Extraction metadata", "Value"])
    writer.writerows([[safe_cell(cell) for cell in row] for row in metadata(result)])
    return stream.getvalue().encode("utf-8-sig")


def export_xlsx(result: AnalysisResult) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Extracted fields"
    sheet.append(HEADERS)
    for row in field_rows(result):
        sheet.append([excel_cell(cell) for cell in row])
    findings = workbook.create_sheet("Review findings")
    findings.append(["Field", "Severity", "Code", "Message"])
    for finding in result.findings:
        findings.append(
            [
                excel_cell(value)
                for value in [finding.field, finding.severity, finding.code, finding.message]
            ]
        )
    audit = workbook.create_sheet("Extraction metadata")
    audit.append(["Property", "Value"])
    for row in metadata(result):
        audit.append([excel_cell(cell) for cell in row])
    for tab in workbook:
        tab.freeze_panes = "A2"
        tab.auto_filter.ref = tab.dimensions
        for cell in tab[1]:
            cell.fill = PatternFill("solid", fgColor="162D2B")
            cell.font = Font(color="FFFFFF", bold=True)
        for column in tab.columns:
            letter = column[0].column_letter
            tab.column_dimensions[letter].width = min(
                64, max(18, max(len(str(c.value or "")) for c in column) + 2)
            )
        for row in tab.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()
