from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.errors import AnalysisError
from app.pipeline import DocumentInput, Pipeline
from app.storage import PipelineStore

router = APIRouter()
ROOT = Path(__file__).parent
DEMO_FILES = ["complete-agreement.pdf", "northstar-services.pdf", "conflicting-agreement.pdf"]


def pipeline() -> Pipeline:
    settings = get_settings()
    return Pipeline(PipelineStore(settings.pipeline_db_path), settings)


@router.get("/pipeline", include_in_schema=False)
async def pipeline_page():
    return FileResponse(ROOT / "static/pipeline.html")


@router.get("/case-study", include_in_schema=False)
async def case_study():
    return FileResponse(ROOT / "static/case-study.html")


@router.get("/api/pipeline/summary")
async def summary():
    service = await run_in_threadpool(pipeline)
    return await run_in_threadpool(service.store.summary)


@router.post("/api/pipeline/demo")
async def demo_batch():
    service = await run_in_threadpool(pipeline)
    inputs = [DocumentInput(name, (ROOT / "samples" / name).read_bytes()) for name in DEMO_FILES]
    return await service.batch(inputs, sample=True)


@router.post("/api/pipeline/batches")
async def upload_batch(
    files: list[UploadFile] = File(...),
    mode: Literal["local", "openai"] = Form("local"),
    persist_consent: bool = Form(False),
    provider_consent: bool = Form(False),
):
    try:
        if not persist_consent:
            raise AnalysisError(
                "persistence_consent_required",
                "Batch mode saves PDF bytes, extracted text and results in local SQLite. Explicit persistence consent is required.",
            )
        if mode == "openai" and not provider_consent:
            raise AnalysisError(
                "provider_consent_required",
                "LLM extraction sends document text to OpenAI. Explicit provider consent is required.",
            )
        if not 1 <= len(files) <= 10:
            raise AnalysisError("batch_count", "Choose between 1 and 10 files per batch.")
        inputs = []
        total = 0
        maximum = get_settings().max_upload_bytes
        for file in files:
            content = await file.read(maximum - total + 1)
            total += len(content)
            if total > maximum:
                raise AnalysisError(
                    "batch_too_large", "The combined batch must be at most 10 MB.", 413
                )
            inputs.append(DocumentInput(file.filename or "contract.pdf", content))
    finally:
        for file in files:
            await file.close()
    service = await run_in_threadpool(pipeline)
    return await service.batch(inputs, mode)


@router.get("/api/pipeline/batches/{batch_id}")
async def get_batch(batch_id: str):
    service = await run_in_threadpool(pipeline)
    return await run_in_threadpool(service.store.batch, batch_id)


@router.get("/api/pipeline/runs/{run_id}/lineage")
async def lineage(run_id: str):
    service = await run_in_threadpool(pipeline)
    return await run_in_threadpool(service.store.lineage, run_id)


@router.get("/api/pipeline/runs/{run_id}/result")
async def saved_result(run_id: str):
    service = await run_in_threadpool(pipeline)
    return await run_in_threadpool(service.store.result, run_id)


@router.post("/api/pipeline/runs/{run_id}/retry")
async def retry(run_id: str):
    service = await run_in_threadpool(pipeline)
    return await service.process_run(run_id, retry_failed=True)


@router.get("/api/evaluation")
async def evaluation():
    path = ROOT / "benchmark/local-report.json"
    if not path.is_file():
        raise AnalysisError(
            "evaluation_not_available",
            "No measured evaluation report is available. Run the evaluation command first.",
            404,
        )
    return FileResponse(path, media_type="application/json")
