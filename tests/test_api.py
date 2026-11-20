import csv
import io
import json

import pytest
from openpyxl import load_workbook
from pypdf import PdfReader, PdfWriter


def test_home_health_and_api_docs(client):
    assert client.get("/").status_code == 200
    assert client.get("/api/health").json()["ai_available"] is False
    assert client.get("/docs").status_code == 200
    response = client.get("/static/app.js")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    "sample,status",
    [("complete", "checks_passed"), ("review", "needs_review"), ("invalid", "needs_review")],
)
def test_demo_runs_real_pdf_extraction(client, sample, status):
    response = client.post("/api/demo", json={"sample": sample})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["sample"] is True
    assert result["mode"] == "local"
    assert result["page_count"] == 2
    assert result["status"] == status
    assert len(result["fields"]) == 11
    assert len(result["document_id"]) == 64
    if sample == "complete":
        assert all(f["status"] == "supported" for f in result["fields"])
        assert not result["findings"]
    elif sample == "invalid":
        fields = {f["key"]: f for f in result["fields"]}
        assert fields["end_date"]["status"] == "invalid"
        assert fields["total_value"]["status"] == "invalid"
        assert fields["payment_terms"]["status"] == "uncertain"


def test_upload_uses_content_and_sanitizes_filename(client, sample_bytes):
    response = client.post(
        "/api/analyze",
        files={"file": ("../../test.pdf", sample_bytes, "application/pdf")},
        data={"mode": "local"},
    )
    assert response.status_code == 200
    assert response.json()["sample"] is False
    assert response.json()["filename"] == "test.pdf"
    assert response.json()["status"] == "checks_passed"


@pytest.mark.parametrize(
    "content,code",
    [
        (b"", "empty_file"),
        (b"not really a pdf", "invalid_pdf"),
        (b"%PDF-1.7\ninvalid", "unreadable_pdf"),
    ],
)
def test_bad_uploads_have_actionable_errors(client, content, code):
    response = client.post("/api/analyze", files={"file": ("fake.pdf", content, "application/pdf")})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code


def test_scanned_or_blank_pdf_requires_ocr(client):
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    stream = io.BytesIO()
    writer.write(stream)
    response = client.post("/api/analyze", files={"file": ("scan.pdf", stream.getvalue())})
    assert response.json()["error"]["code"] == "ocr_required"


def test_mixed_pdf_reports_unread_pages(client, sample_bytes):
    writer = PdfWriter()
    for page in PdfReader(io.BytesIO(sample_bytes)).pages:
        writer.add_page(page)
    writer.add_blank_page(width=595, height=842)
    stream = io.BytesIO()
    writer.write(stream)
    result = client.post("/api/analyze", files={"file": ("mixed.pdf", stream.getvalue())}).json()
    assert result["status"] == "needs_review"
    assert any("not analyzed" in notice for notice in result["notices"])


def test_encrypted_pdf_rejected(client, sample_bytes):
    writer = PdfWriter(clone_from=io.BytesIO(sample_bytes))
    writer.encrypt("secret")
    stream = io.BytesIO()
    writer.write(stream)
    response = client.post("/api/analyze", files={"file": ("protected.pdf", stream.getvalue())})
    assert response.json()["error"]["code"] == "encrypted_pdf"


def test_too_many_pages_rejected(client):
    writer = PdfWriter()
    for _ in range(41):
        writer.add_blank_page(width=100, height=100)
    stream = io.BytesIO()
    writer.write(stream)
    response = client.post("/api/analyze", files={"file": ("long.pdf", stream.getvalue())})
    assert response.json()["error"]["code"] == "too_many_pages"


def test_size_limit(client):
    response = client.post(
        "/api/analyze", files={"file": ("large.pdf", b"%PDF-" + b"0" * (10 * 1024 * 1024))}
    )
    assert response.status_code == 413


def test_disabled_ai_returns_configuration_error(client, sample_bytes):
    response = client.post(
        "/api/analyze", files={"file": ("contract.pdf", sample_bytes)}, data={"mode": "openai"}
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ai_not_configured"


def test_invalid_request_does_not_echo_contract_payload(client):
    response = client.post("/api/export/json", json={"private_contract": "SENSITIVE SENTINEL"})
    assert response.status_code == 422
    assert "SENSITIVE SENTINEL" not in response.text
    assert client.post("/api/demo", json={"sample": "../../etc/passwd"}).status_code == 422


@pytest.mark.parametrize("format", ["json", "csv", "xlsx"])
def test_exports_preserve_missing_values_statuses_and_evidence(client, format):
    result = client.post("/api/demo", json={"sample": "review"}).json()
    response = client.post("/api/export/" + format, json=result)
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    if format == "json":
        exported = json.loads(response.content)
        assert exported == result
        assert next(f for f in exported["fields"] if f["key"] == "end_date")["value"] is None
    elif format == "csv":
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
        assert rows[0] == [
            "Field",
            "Value",
            "Status",
            "Required",
            "Issues",
            "Source pages",
            "Evidence",
        ]
        assert any("uncertain" in row for row in rows)
        assert any("missing" in row for row in rows)
        assert any("Document SHA-256" in row for row in rows)
    else:
        workbook = load_workbook(io.BytesIO(response.content))
        assert workbook.sheetnames == ["Extracted fields", "Review findings", "Extraction metadata"]
        assert workbook["Extracted fields"].max_row == 12
        assert workbook["Review findings"].max_row > 1


@pytest.mark.parametrize(
    "payload", ['=HYPERLINK("https://evil.example")', "   +1+1", "@SUM(1)", "\t=1+1"]
)
def test_spreadsheet_formula_injection_is_escaped(client, payload):
    result = client.post("/api/demo", json={"sample": "complete"}).json()
    result["fields"][0]["value"] = payload
    csv_response = client.post("/api/export/csv", json=result)
    rows = list(csv.reader(io.StringIO(csv_response.content.decode("utf-8-sig"))))
    assert rows[1][1] == "'" + payload
    xlsx_response = client.post("/api/export/xlsx", json=result)
    workbook = load_workbook(io.BytesIO(xlsx_response.content))
    cell = workbook["Extracted fields"]["B2"]
    assert cell.data_type == "s"
    assert cell.value == "'" + payload


@pytest.mark.parametrize(
    "value,code", [("A" * 32768, "excel_cell_too_long"), ("Bad\x01text", "excel_unsupported_text")]
)
def test_excel_does_not_silently_drop_or_truncate_text(client, value, code):
    result = client.post("/api/demo", json={"sample": "complete"}).json()
    result["fields"][0]["value"] = value
    response = client.post("/api/export/xlsx", json=result)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code
    assert client.post("/api/export/json", json=result).json()["fields"][0]["value"] == value
