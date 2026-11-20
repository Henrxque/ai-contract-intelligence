"""Transparent field-level evaluation against authored answers, independent of model claims."""

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from app.analysis import PIPELINE_VERSION, analyze_document
from app.config import Settings, get_settings
from app.errors import AnalysisError
from app.models import AnalysisResult

ROOT = Path(__file__).parent


def normalized(value: str | None) -> str | None:
    # Deliberately strict: ignore whitespace and case, not missing clause conditions.
    return " ".join(value.casefold().split()) if value is not None else None


def score(result: AnalysisResult, expected: dict) -> dict:
    actual = {field.key: field for field in result.fields}
    rows = []
    for key, target in expected["expected_values"].items():
        field = actual.get(key)
        value = field.value if field else None
        status = field.status if field else "missing"
        matched = normalized(value) == normalized(target)
        source = {page.number: normalized(page.text) for page in result.pages}
        grounded = bool(field and field.evidence) and all(
            normalized(e.quote) in (source.get(e.page) or "") for e in field.evidence
        )
        rows.append(
            {
                "field": key,
                "expected_value": target,
                "actual_value": value,
                "expected_status": expected["expected_statuses"][key],
                "actual_status": status,
                "value_match": matched,
                "status_match": status == expected["expected_statuses"][key],
                "quote_grounded": grounded if value is not None else None,
                "false_supported": status == "supported" and (not matched or not grounded),
            }
        )
    return {
        "filename": expected["filename"],
        "document_id": result.document_id,
        "elapsed_ms": result.elapsed_ms,
        "quality_status": result.status,
        "token_usage": result.token_usage.model_dump() if result.token_usage else None,
        "fields": rows,
    }


def ratio(numerator: int, denominator: int) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 6) if denominator else None,
    }


async def evaluate(
    mode: Literal["local", "openai"] = "local",
    settings: Settings | None = None,
    manifest_path: Path | None = None,
) -> dict:
    settings = settings or get_settings()
    path = manifest_path or ROOT / "benchmark/ground-truth.json"
    manifest_bytes = path.read_bytes()
    manifest = json.loads(manifest_bytes)
    started = time.perf_counter()
    documents = []
    for case in manifest["cases"]:
        filename = case["filename"]
        if Path(filename).name != filename or "/" in filename or "\\" in filename:
            raise AnalysisError(
                "invalid_benchmark", "Benchmark filenames must be plain sample filenames."
            )
        content = (ROOT / "samples" / filename).read_bytes()
        if hashlib.sha256(content).hexdigest() != case["sha256"]:
            raise AnalysisError(
                "benchmark_hash_mismatch",
                "A benchmark PDF changed. Review the fixture and its expected answers before regenerating the manifest.",
            )
        artifacts = await analyze_document(content, filename, mode, sample=True, settings=settings)
        documents.append(score(artifacts.result, case))
    rows = [row for document in documents for row in document["fields"]]
    present = [row for row in rows if row["expected_value"] is not None]
    predicted = [row for row in rows if row["actual_value"] is not None]
    correct_present = sum(row["value_match"] and row["actual_value"] is not None for row in present)
    flagged = [row for row in rows if row["expected_status"] in {"uncertain", "invalid"}]
    usages = [
        document["token_usage"] for document in documents if document["token_usage"] is not None
    ]
    return {
        "report_version": "1.0",
        "dataset_id": manifest["dataset_id"],
        "dataset_version": manifest["version"],
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "pipeline_version": PIPELINE_VERSION,
        "mode": mode,
        "model": settings.openai_model if mode == "openai" else None,
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "document_count": len(documents),
        "field_count": len(rows),
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "metrics": {
            "value_exact_match": ratio(sum(row["value_match"] for row in rows), len(rows)),
            "non_null_value_precision": ratio(correct_present, len(predicted)),
            "non_null_value_recall": ratio(correct_present, len(present)),
            "status_accuracy": ratio(sum(row["status_match"] for row in rows), len(rows)),
            "flagged_issue_recall": ratio(
                sum(row["actual_status"] in {"uncertain", "invalid"} for row in flagged),
                len(flagged),
            ),
            "quote_grounding": ratio(
                sum(row["quote_grounded"] is True for row in predicted), len(predicted)
            ),
            "false_supported_fields": sum(row["false_supported"] for row in rows),
            "missing_predictions": sum(row["actual_value"] is None for row in present),
        },
        "usage": {
            key: sum(u[key] for u in usages)
            for key in ["input_tokens", "output_tokens", "cached_input_tokens"]
        }
        if usages
        else None,
        "usage_document_coverage": ratio(len(usages), len(documents)),
        "cost_usd": None,
        "limitations": [
            "Small authored synthetic development benchmark, not an unseen real-world accuracy estimate.",
            "Local mode uses deterministic rules; no LLM call or provider cost occurred in this report."
            if mode == "local"
            else "Live-provider extraction; token counts are reported when available. Monetary cost was not measured.",
            "Exact match accepts whitespace/case normalization only. Equivalent paraphrases count as mismatches.",
            "Quote grounding measures text correspondence, not semantic correctness.",
        ],
        "documents": documents,
    }
