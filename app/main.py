from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool

from app.analysis import analyze
from app.config import get_settings
from app.errors import AnalysisError
from app.exports import export_csv, export_json, export_xlsx
from app.models import AnalysisResult
from app.pipeline_api import router as pipeline_router


ROOT = Path(__file__).parent
SAMPLES = {
    "review": "northstar-services.pdf",
    "complete": "complete-agreement.pdf",
    "invalid": "conflicting-agreement.pdf",
}
app = FastAPI(
    title="AI Contract Intelligence",
    version="0.2.0",
    docs_url=None,
    redoc_url=None,
    description="PDF → evidence-backed extraction → deterministic checks → review-ready exports.",
)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
app.include_router(pipeline_router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    declared_length = request.headers.get("content-length", "0")
    try:
        too_large = int(declared_length) > 12 * 1024 * 1024
    except ValueError:
        return JSONResponse(
            {"error": {"code": "invalid_request", "message": "Invalid content length."}},
            status_code=400,
        )
    if too_large:
        return JSONResponse(
            {"error": {"code": "request_too_large", "message": "Request exceeds the 12 MB limit."}},
            status_code=413,
        )
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(AnalysisError)
async def analysis_error(request: Request, exc: AnalysisError):
    return JSONResponse(
        {"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status_code
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(
        {
            "error": {
                "code": "invalid_request",
                "message": "Request format is invalid. Check the file, mode or export data.",
            }
        },
        status_code=422,
    )


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
async def health():
    settings = get_settings()
    return {
        "status": "ok",
        "ai_available": settings.ai_available,
        "ai_model": settings.openai_model if settings.ai_available else None,
        "max_upload_mb": 10,
        "max_pages": settings.max_pages,
    }


@app.get("/docs", include_in_schema=False)
async def api_reference():
    return FileResponse(ROOT / "static" / "api.html")


@app.post("/api/analyze", response_model=AnalysisResult)
async def analyze_upload(
    file: UploadFile = File(...), mode: Literal["local", "openai"] = Form("local")
):
    try:
        data = await file.read(get_settings().max_upload_bytes + 1)
    finally:
        await file.close()
    filename = (file.filename or "contract.pdf").replace("\\", "/").split("/")[-1][:160]
    return await analyze(data, filename, mode)


class DemoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample: Literal["review", "complete", "invalid"] = "review"


@app.post("/api/demo", response_model=AnalysisResult)
async def demo(body: DemoRequest):
    filename = SAMPLES[body.sample]
    return await analyze((ROOT / "samples" / filename).read_bytes(), filename, "local", sample=True)


@app.get("/api/samples/{sample}")
async def sample_download(sample: Literal["review", "complete", "invalid"]):
    filename = SAMPLES[sample]
    return FileResponse(
        ROOT / "samples" / filename, media_type="application/pdf", filename=filename
    )


@app.post("/api/export/{format}")
async def export(format: Literal["json", "csv", "xlsx"], result: AnalysisResult):
    # Stateless export: only the user's submitted result is transformed, never a stored record.
    exporters = {
        "json": (export_json, "application/json"),
        "csv": (export_csv, "text/csv; charset=utf-8"),
        "xlsx": (export_xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    }
    fn, media_type = exporters[format]
    content = await run_in_threadpool(fn, result)
    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="contract-analysis.{format}"'},
    )
