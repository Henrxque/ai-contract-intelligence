import asyncio
import json
from pathlib import Path

import pytest

from app.analysis import analyze_document
from app.errors import AnalysisError
from app.evaluation import evaluate, ratio, score


def test_benchmark_measures_failures_not_just_successes():
    report = asyncio.run(evaluate())
    assert report["document_count"] == 8
    assert report["field_count"] == 88
    assert report["mode"] == "local"
    assert report["usage"] is None
    assert report["cost_usd"] is None
    assert report["metrics"]["value_exact_match"]["numerator"] < report["field_count"]
    assert report["metrics"]["missing_predictions"] == 11
    assert report["metrics"]["false_supported_fields"] == 0
    prose = next(doc for doc in report["documents"] if doc["filename"] == "prose-agreement.pdf")
    assert all(not row["value_match"] for row in prose["fields"])
    wrapped = next(doc for doc in report["documents"] if doc["filename"] == "wrapped-agreement.pdf")
    payment = next(f for f in wrapped["fields"] if f["field"] == "payment_terms")
    assert payment["value_match"] is False
    assert payment["actual_status"] == "uncertain"


def test_evaluation_rejects_modified_pdf_manifest(tmp_path):
    source = Path(__file__).resolve().parents[1] / "app/benchmark/ground-truth.json"
    manifest = json.loads(source.read_text(encoding="utf-8"))
    manifest["cases"][0]["sha256"] = "wrong"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AnalysisError) as exc:
        asyncio.run(evaluate(manifest_path=path))
    assert exc.value.code == "benchmark_hash_mismatch"


def test_evaluator_counts_false_supported_and_fabricated_quotes(sample_bytes):
    result = asyncio.run(analyze_document(sample_bytes, "contract.pdf", "local")).result
    field = result.fields[0]
    target = {
        "filename": "contract.pdf",
        "expected_values": {field.key: field.value},
        "expected_statuses": {field.key: "supported"},
    }
    field.value = "Invented provider"
    field.evidence[0].quote = "Fabricated evidence"
    scored = score(result, target)["fields"][0]
    assert scored["false_supported"] is True
    assert scored["quote_grounded"] is False


def test_zero_denominator_is_unknown_not_zero_or_perfect():
    assert ratio(0, 0)["rate"] is None


def test_published_report_identifies_baseline_and_known_limitations(client):
    report = client.get("/api/evaluation").json()
    assert report["model"] is None
    assert "synthetic" in report["dataset_id"]
    assert "real-world" in report["limitations"][0]
