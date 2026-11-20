"""SQLite repository. Every state transition uses a short, fenced transaction."""

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.analysis import AnalysisArtifacts, PIPELINE_VERSION
from app.errors import AnalysisError
from app.models import AnalysisResult, Extraction, SourcePage


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PipelineStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection(transaction=False) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                (Path(__file__).parent / "sql/001_pipeline.sql").read_text(encoding="utf-8")
            )
            db.execute("INSERT OR IGNORE INTO schema_migrations VALUES(1,?)", (now(),))

    @contextmanager
    def connection(self, write: bool = False, transaction: bool = True):
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            if transaction:
                db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            if db.in_transaction:
                db.commit()
        except BaseException:
            if db.in_transaction:
                db.rollback()
            raise
        finally:
            db.close()

    def register(self, content: bytes, filename: str, config: dict) -> str:
        document_id = hashlib.sha256(content).hexdigest()
        config_json = json.dumps(config, sort_keys=True, separators=(",", ":"))
        config_hash = hashlib.sha256(config_json.encode()).hexdigest()
        stamp = now()
        with self.connection(write=True) as db:
            db.execute(
                "INSERT OR IGNORE INTO documents VALUES(?,?,?,?,?)",
                (document_id, filename, content, len(content), stamp),
            )
            db.execute(
                """INSERT OR IGNORE INTO runs
                (run_id,document_id,config_hash,config_json,pipeline_version,mode,provider_model,sample,state,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?, 'queued',?,?)""",
                (
                    uuid4().hex,
                    document_id,
                    config_hash,
                    config_json,
                    PIPELINE_VERSION,
                    config["mode"],
                    config["model"],
                    int(config["sample"]),
                    stamp,
                    stamp,
                ),
            )
            return db.execute(
                "SELECT run_id FROM runs WHERE document_id=? AND config_hash=?",
                (document_id, config_hash),
            ).fetchone()[0]

    def claim(self, run_id: str, retry_failed: bool = False) -> tuple[str | None, str]:
        stamp = now()
        with self.connection(write=True) as db:
            run = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise AnalysisError("run_not_found", "Pipeline run was not found.", 404)
            if run["state"] == "succeeded":
                return None, "cached"
            if run["state"] == "failed" and not retry_failed:
                return None, "failed_not_retried"
            if run["state"] == "running":
                if run["lease_expires"] > time.time():
                    return None, "in_progress"
                db.execute(
                    "UPDATE attempts SET state='failed',finished_at=?,error_code='lease_expired',error_message='Worker lease expired before completion.' WHERE run_id=? AND state='running'",
                    (stamp, run_id),
                )
            if run["attempt_count"] >= run["max_attempts"]:
                db.execute(
                    "UPDATE runs SET state='failed',lease_token=NULL,lease_expires=NULL,error_code='retry_limit',error_message='Maximum of three attempts reached.',updated_at=? WHERE run_id=?",
                    (stamp, run_id),
                )
                return None, "retry_limit"
            token = uuid4().hex
            attempt = run["attempt_count"] + 1
            db.execute(
                "UPDATE runs SET state='running',attempt_count=?,lease_token=?,lease_expires=?,error_code=NULL,error_message=NULL,updated_at=? WHERE run_id=?",
                (attempt, token, time.time() + 300, stamp, run_id),
            )
            db.execute(
                "INSERT INTO attempts(run_id,attempt_number,state,started_at) VALUES(?,?,'running',?)",
                (run_id, attempt, stamp),
            )
            return token, "processed"

    @staticmethod
    def assert_lease(db, run_id: str, token: str):
        row = db.execute(
            "SELECT attempt_count FROM runs WHERE run_id=? AND state='running' AND lease_token=? AND lease_expires>?",
            (run_id, token, time.time()),
        ).fetchone()
        if row is None:
            raise AnalysisError(
                "lease_lost",
                "This worker no longer owns the run. Its output was not accepted.",
                409,
            )
        return row[0]

    def checkpoint(
        self, run_id: str, token: str, pages: list[SourcePage], extraction: Extraction | None
    ):
        with self.connection(write=True) as db:
            self.assert_lease(db, run_id, token)
            db.execute(
                """INSERT INTO extraction_staging VALUES(?,?,?,?)
                ON CONFLICT(run_id) DO UPDATE SET pages_json=excluded.pages_json,
                extraction_json=excluded.extraction_json,updated_at=excluded.updated_at""",
                (
                    run_id,
                    json.dumps([p.model_dump() for p in pages]),
                    extraction.model_dump_json() if extraction else None,
                    now(),
                ),
            )

    def complete(self, run_id: str, token: str, artifacts: AnalysisArtifacts):
        result = artifacts.result
        stamp = now()
        with self.connection(write=True) as db:
            attempt = self.assert_lease(db, run_id, token)
            db.execute(
                "INSERT INTO analyses VALUES(?,?,?,?,?)",
                (run_id, result.model_dump_json(), result.status, result.elapsed_ms, stamp),
            )
            for field in result.fields:
                db.execute(
                    "INSERT INTO contract_fields VALUES(?,?,?,?,?,?,?)",
                    (
                        run_id,
                        field.key,
                        field.label,
                        field.group,
                        field.value,
                        field.status,
                        int(field.required),
                    ),
                )
                db.executemany(
                    "INSERT INTO field_evidence VALUES(?,?,?,?,?)",
                    [(run_id, field.key, i, e.page, e.quote) for i, e in enumerate(field.evidence)],
                )
            db.executemany(
                "INSERT INTO review_findings VALUES(?,?,?,?,?,?)",
                [
                    (run_id, i, f.field, f.severity, f.code, f.message)
                    for i, f in enumerate(result.findings)
                ],
            )
            db.execute(
                "UPDATE attempts SET state='succeeded',finished_at=? WHERE run_id=? AND attempt_number=?",
                (stamp, run_id, attempt),
            )
            db.execute(
                "UPDATE runs SET state='succeeded',lease_token=NULL,lease_expires=NULL,updated_at=? WHERE run_id=?",
                (stamp, run_id),
            )

    def fail(self, run_id: str, token: str, code: str, message: str):
        stamp = now()
        with self.connection(write=True) as db:
            row = db.execute(
                "SELECT attempt_count FROM runs WHERE run_id=? AND state='running' AND lease_token=?",
                (run_id, token),
            ).fetchone()
            if row is None:
                return
            db.execute(
                "UPDATE attempts SET state='failed',finished_at=?,error_code=?,error_message=? WHERE run_id=? AND attempt_number=?",
                (stamp, code, message, run_id, row[0]),
            )
            db.execute(
                "UPDATE runs SET state='failed',error_code=?,error_message=?,lease_token=NULL,lease_expires=NULL,updated_at=? WHERE run_id=?",
                (code, message, stamp, run_id),
            )

    def run(self, run_id: str) -> dict:
        with self.connection() as db:
            row = db.execute(
                """SELECT r.*, d.original_filename, a.quality_status, a.elapsed_ms
                FROM runs r JOIN documents d USING(document_id)
                LEFT JOIN analyses a USING(run_id) WHERE run_id=?""",
                (run_id,),
            ).fetchone()
            if row is None:
                raise AnalysisError("run_not_found", "Pipeline run was not found.", 404)
            result = dict(row)
            result.pop("lease_token")
            result.pop("lease_expires")
            result["config"] = json.loads(result.pop("config_json"))
            return result

    def input(self, run_id: str) -> tuple[bytes, str]:
        with self.connection() as db:
            row = db.execute(
                "SELECT d.content,d.original_filename FROM documents d JOIN runs r USING(document_id) WHERE r.run_id=?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise AnalysisError("run_not_found", "Pipeline run was not found.", 404)
            return bytes(row[0]), row[1]

    def result(self, run_id: str) -> AnalysisResult:
        with self.connection() as db:
            row = db.execute(
                "SELECT result_json FROM analyses WHERE run_id=?", (run_id,)
            ).fetchone()
            if row is None:
                raise AnalysisError(
                    "result_not_available", "This run does not have a completed analysis.", 404
                )
            return AnalysisResult.model_validate_json(row[0])

    def lineage(self, run_id: str) -> dict:
        run = self.run(run_id)
        with self.connection() as db:
            attempts = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM attempts WHERE run_id=? ORDER BY attempt_number", (run_id,)
                )
            ]
            staging = db.execute(
                "SELECT * FROM extraction_staging WHERE run_id=?", (run_id,)
            ).fetchone()
        return {
            "run": run,
            "attempts": attempts,
            "staging": {
                "pages": json.loads(staging["pages_json"]),
                "extraction": json.loads(staging["extraction_json"])
                if staging["extraction_json"]
                else None,
            }
            if staging
            else None,
        }

    def create_batch(self, mode: str, sample: bool) -> str:
        batch_id = uuid4().hex
        with self.connection(write=True) as db:
            db.execute("INSERT INTO batches VALUES(?,?,?,?)", (batch_id, mode, int(sample), now()))
        return batch_id

    def add_item(self, batch_id: str, ordinal: int, filename: str, run_id: str):
        with self.connection(write=True) as db:
            db.execute(
                "INSERT INTO batch_items(batch_id,ordinal,input_filename,run_id) VALUES(?,?,?,?)",
                (batch_id, ordinal, filename, run_id),
            )

    def finish_item(self, batch_id: str, ordinal: int, disposition: str, state: str):
        with self.connection(write=True) as db:
            db.execute(
                "UPDATE batch_items SET disposition=?,observed_state=? WHERE batch_id=? AND ordinal=?",
                (disposition, state, batch_id, ordinal),
            )

    def batch(self, batch_id: str) -> dict:
        with self.connection() as db:
            batch = db.execute("SELECT * FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
            if batch is None:
                raise AnalysisError("batch_not_found", "Batch was not found.", 404)
            items = [
                dict(r)
                for r in db.execute(
                    """SELECT i.*,r.state AS current_state,r.attempt_count,r.error_code,a.quality_status
                FROM batch_items i JOIN runs r USING(run_id) LEFT JOIN analyses a USING(run_id)
                WHERE batch_id=? ORDER BY ordinal""",
                    (batch_id,),
                )
            ]
        return {
            **dict(batch),
            "items": items,
            "processed": sum(i["disposition"] == "processed" for i in items),
            "cached": sum(i["disposition"] == "cached" for i in items),
            "failed": sum(i["observed_state"] == "failed" for i in items),
        }

    def summary(self) -> dict:
        with self.connection() as db:
            counts = {
                table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in [
                    "documents",
                    "runs",
                    "attempts",
                    "analyses",
                    "contract_fields",
                    "field_evidence",
                    "review_findings",
                    "batches",
                ]
            }
            states = {
                r[0]: r[1] for r in db.execute("SELECT state,COUNT(*) FROM runs GROUP BY state")
            }
            quality = {
                r[0]: r[1]
                for r in db.execute(
                    "SELECT quality_status,COUNT(*) FROM analyses GROUP BY quality_status"
                )
            }
            recent = [
                dict(r)
                for r in db.execute("""SELECT r.run_id,r.document_id,r.mode,r.provider_model,r.sample,r.state,r.attempt_count,
                r.error_code,r.error_message,r.updated_at,d.original_filename,a.quality_status,a.elapsed_ms
                FROM runs r JOIN documents d USING(document_id) LEFT JOIN analyses a USING(run_id)
                ORDER BY r.updated_at DESC,r.run_id LIMIT 30""")
            ]
        return {
            "pipeline_version": PIPELINE_VERSION,
            "storage": "SQLite",
            "counts": counts,
            "states": states,
            "quality": quality,
            "recent_runs": recent,
        }
