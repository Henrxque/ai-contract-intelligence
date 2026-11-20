"""python -m app.cli: reproducible batch processing and evaluation."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.config import get_settings
from app.errors import AnalysisError
from app.pipeline import DocumentInput, Pipeline
from app.storage import PipelineStore


def write_report(report: dict, path: Path | None):
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


async def run(args) -> int:
    settings = get_settings()
    if args.command == "evaluate":
        from app.evaluation import evaluate

        report = await evaluate(args.mode, settings=settings)
        write_report(report, args.output)
        return 0
    store = PipelineStore(args.database or settings.pipeline_db_path)
    service = Pipeline(store, settings)
    if args.command == "inspect":
        write_report(store.summary(), args.output)
        return 0
    if args.command == "retry":
        report = await service.process_run(args.run_id, retry_failed=True)
        write_report(report, args.output)
        return 1 if report["run"]["state"] == "failed" else 0
    files = sorted(args.folder.glob("*.pdf"))
    if not 1 <= len(files) <= 10:
        raise AnalysisError("batch_count", "The folder must contain between 1 and 10 .pdf files.")
    inputs = []
    total = 0
    for path in files:
        with path.open("rb") as stream:
            content = stream.read(settings.max_upload_bytes - total + 1)
        total += len(content)
        if total > settings.max_upload_bytes:
            raise AnalysisError("batch_too_large", "The combined batch must be at most 10 MB.")
        inputs.append(DocumentInput(path.name, content))
    report = await service.batch(inputs, args.mode, args.synthetic, args.retry_failed)
    write_report(report, args.output)
    return 1 if report["failed"] else 0


def main():
    parser = argparse.ArgumentParser(
        description="Contract data pipeline: durable batch processing, SQL lineage and extraction evaluation."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    batch = commands.add_parser(
        "batch", help="Process up to 10 PDFs (10 MB combined) and persist them to SQLite."
    )
    batch.add_argument("folder", type=Path)
    batch.add_argument("--mode", choices=["local", "openai"], default="local")
    batch.add_argument(
        "--synthetic", action="store_true", help="Mark all documents as fictional fixtures."
    )
    batch.add_argument("--retry-failed", action="store_true")
    retry = commands.add_parser("retry", help="Retry a failed/expired run, up to three attempts.")
    retry.add_argument("run_id")
    inspect = commands.add_parser("inspect", help="Read persisted counts and recent run states.")
    evaluation = commands.add_parser(
        "evaluate",
        help="Measure extraction against the versioned synthetic benchmark (no DB writes).",
    )
    evaluation.add_argument("--mode", choices=["local", "openai"], default="local")
    for command in [batch, retry, inspect]:
        command.add_argument("--database", type=Path)
    for command in [batch, retry, inspect, evaluation]:
        command.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        code = asyncio.run(run(args))
    except (AnalysisError, OSError) as exc:
        payload = {
            "error": {
                "code": exc.code if isinstance(exc, AnalysisError) else "filesystem_error",
                "message": str(exc),
            }
        }
        print(json.dumps(payload), file=sys.stderr)
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
