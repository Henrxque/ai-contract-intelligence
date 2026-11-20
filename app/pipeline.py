"""Bounded batch orchestration with content-addressed inputs and explicit retries."""

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Literal

from starlette.concurrency import run_in_threadpool

from app.analysis import PIPELINE_VERSION, analyze_document
from app.config import Settings, get_settings
from app.errors import AnalysisError
from app.extractors import LABELS, SYSTEM_PROMPT
from app.models import FIELD_SPECS
from app.storage import PipelineStore

logger = logging.getLogger(__name__)


@dataclass
class DocumentInput:
    filename: str
    content: bytes


def extraction_config(mode: Literal["local", "openai"], sample: bool, settings: Settings) -> dict:
    return {
        "pipeline_version": PIPELINE_VERSION,
        "mode": mode,
        "model": settings.openai_model if mode == "openai" else None,
        "sample": sample,
        "extractor_hash": hashlib.sha256(
            (SYSTEM_PROMPT if mode == "openai" else json.dumps(LABELS, sort_keys=True)).encode()
        ).hexdigest(),
        "policy_hash": hashlib.sha256(json.dumps(FIELD_SPECS, sort_keys=True).encode()).hexdigest(),
    }


class Pipeline:
    def __init__(self, store: PipelineStore, settings: Settings | None = None):
        self.store = store
        self.settings = settings or get_settings()

    async def process_run(self, run_id: str, retry_failed: bool = False) -> dict:
        token, disposition = await run_in_threadpool(self.store.claim, run_id, retry_failed)
        if token:
            try:
                run = await run_in_threadpool(self.store.run, run_id)
                data, filename = await run_in_threadpool(self.store.input, run_id)
                expected = extraction_config(run["mode"], bool(run["sample"]), self.settings)
                if run["config"] != expected:
                    raise AnalysisError(
                        "pipeline_version_changed",
                        "The extractor configuration changed. Submit a new batch to create a versioned run.",
                        409,
                    )
                artifacts = await analyze_document(
                    data,
                    filename,
                    run["mode"],
                    bool(run["sample"]),
                    self.settings,
                    checkpoint=lambda pages, raw: self.store.checkpoint(run_id, token, pages, raw),
                )
                await run_in_threadpool(self.store.complete, run_id, token, artifacts)
            except AnalysisError as exc:
                await run_in_threadpool(self.store.fail, run_id, token, exc.code, exc.message)
            except Exception as exc:
                logger.error("Pipeline run %s failed: %s", run_id, type(exc).__name__)
                await run_in_threadpool(
                    self.store.fail,
                    run_id,
                    token,
                    "internal_error",
                    "Processing failed before a result was committed. Inspect the server configuration and retry.",
                )
        return {"disposition": disposition, "run": await run_in_threadpool(self.store.run, run_id)}

    async def batch(
        self,
        inputs: list[DocumentInput],
        mode: Literal["local", "openai"] = "local",
        sample: bool = False,
        retry_failed: bool = False,
    ) -> dict:
        if not inputs or len(inputs) > 10:
            raise AnalysisError("batch_count", "Choose between 1 and 10 PDF files per batch.")
        if sum(len(item.content) for item in inputs) > self.settings.max_upload_bytes:
            raise AnalysisError("batch_too_large", "The combined batch must be at most 10 MB.", 413)
        config = extraction_config(mode, sample, self.settings)
        batch_id = await run_in_threadpool(self.store.create_batch, mode, sample)
        registered = []
        for index, item in enumerate(inputs):
            filename = item.filename.replace("\\", "/").split("/")[-1][:160] or "contract.pdf"
            run_id = await run_in_threadpool(self.store.register, item.content, filename, config)
            await run_in_threadpool(self.store.add_item, batch_id, index, filename, run_id)
            registered.append((index, run_id))
        # Register all inputs before execution so interrupted batches can be resumed.
        for index, run_id in registered:
            outcome = await self.process_run(run_id, retry_failed)
            await run_in_threadpool(
                self.store.finish_item,
                batch_id,
                index,
                outcome["disposition"],
                outcome["run"]["state"],
            )
        return await run_in_threadpool(self.store.batch, batch_id)
