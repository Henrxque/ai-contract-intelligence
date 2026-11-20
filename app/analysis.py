"""Shared extraction engine for transient review, durable batches and evaluation."""

import asyncio
import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from starlette.concurrency import run_in_threadpool

from app.config import Settings, get_settings
from app.extractors import extract_local, extract_openai
from app.models import AnalysisResult, Extraction, SourcePage, TokenUsage
from app.pdf import read_pdf
from app.validation import validate_extraction

PIPELINE_VERSION = "2.0.0"
analysis_slots = asyncio.Semaphore(2)


@dataclass
class AnalysisArtifacts:
    result: AnalysisResult
    extraction: Extraction


async def analyze_document(
    data: bytes,
    filename: str,
    mode: Literal["local", "openai"],
    sample: bool = False,
    settings: Settings | None = None,
    checkpoint: Callable[[list[SourcePage], Extraction | None], None] | None = None,
) -> AnalysisArtifacts:
    settings = settings or get_settings()
    started = time.perf_counter()
    usage = {}
    async with analysis_slots:
        pages = await run_in_threadpool(read_pdf, data, settings)
        if checkpoint:
            await run_in_threadpool(checkpoint, pages, None)
        extraction = (
            await extract_openai(pages, settings, usage)
            if mode == "openai"
            else await run_in_threadpool(extract_local, pages)
        )
        if checkpoint:
            await run_in_threadpool(checkpoint, pages, extraction)
        fields, findings = validate_extraction(extraction, pages)
    notices = [
        "Source and format checks do not establish legal validity or extraction completeness. Review before relying on this output."
    ]
    if mode == "local":
        notices.append(
            "Local rules read supported labels followed by a colon on a single line. Other wording or wrapped values may be missed or incomplete. No LLM was used."
        )
    if sample:
        notices.append("Synthetic portfolio sample. All names, amounts and clauses are fictional.")
    blank = [str(p.number) for p in pages if not p.text.strip()]
    if blank:
        notices.append(
            "No text found on page(s) "
            + ", ".join(blank)
            + ". These pages were not analyzed and may require OCR."
        )
    needs_review = bool(blank) or any(
        f.status in {"invalid", "uncertain"} or (f.required and f.status == "missing")
        for f in fields
    )
    result = AnalysisResult(
        document_id=hashlib.sha256(data).hexdigest(),
        filename=filename,
        page_count=len(pages),
        mode=mode,
        provider_model=settings.openai_model if mode == "openai" else None,
        sample=sample,
        analyzed_at=datetime.now(timezone.utc).isoformat(),
        elapsed_ms=round((time.perf_counter() - started) * 1000),
        status="needs_review" if needs_review else "checks_passed",
        fields=fields,
        findings=findings,
        pages=pages,
        notices=notices,
        token_usage=TokenUsage(**usage) if usage else None,
    )
    return AnalysisArtifacts(result=result, extraction=extraction)


async def analyze(
    data: bytes, filename: str, mode: Literal["local", "openai"], sample: bool = False
) -> AnalysisResult:
    return (await analyze_document(data, filename, mode, sample)).result
