# Local pipeline runbook

Run commands from the repository root. Use `.venv/bin/python` instead of `.venv\Scripts\python` on macOS/Linux. Installation is in the README.

## Start and demonstrate

```powershell
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `/case-study` for the presentation, `/pipeline` for persistent batches, or `/` for transient review. Browser batch uploads require persistence consent. Local mode never calls an AI provider.

Default database: `data/pipeline.sqlite3`. Override `PIPELINE_DB_PATH` before starting. Runtime `data/` and SQLite/WAL/SHM files are ignored by Git. The server creates the schema lazily when the durable workflow is used.

## Batch and replay

```powershell
.venv\Scripts\python -m app.cli batch app/samples --synthetic --database data/demo.sqlite3 --output data/first-batch.json
.venv\Scripts\python -m app.cli batch app/samples --synthetic --database data/demo.sqlite3 --output data/replay.json
.venv\Scripts\python -m app.cli inspect --database data/demo.sqlite3
```

Limits: 1–10 `.pdf` files, 10 MB combined. All inputs are registered before execution. Use `--synthetic` only for fictional documents. Ordinary inputs default to non-synthetic.

`processed` counts claimed attempts, including failures; `cached` counts reused successful results; `failed` counts failed outcomes observed in that batch. Batch items retain both their observed state and the run's current state, which can change after retry. CLI returns nonzero for processing failures; quality findings alone do not fail the batch.

## Query the data

The schema is `app/sql/001_pipeline.sql`; examples are in `docs/queries.sql`. Any SQLite client works, or use Python:

```powershell
.venv\Scripts\python -c "import sqlite3; c=sqlite3.connect('data/demo.sqlite3'); print(c.execute('SELECT field_key,value,status FROM accepted_contract_fields').fetchall()); c.close()"
```

`accepted_contract_fields` contains supported fields from contracts whose checks passed. `quality_quarantine` contains **all fields** from completed contracts requiring review. `review_findings` explains the issues. Failed processing has no normalized analysis rows.

## Retry or resume

```powershell
.venv\Scripts\python -m app.cli retry RUN_ID --database data/demo.sqlite3
```

- Queued runs can start immediately.
- Active workers own a five-minute lease; another request reports `in_progress` without a second attempt.
- Expired leases can be reclaimed. The previous attempt is failed and its stale token cannot commit.
- Failed runs retry explicitly, at most three attempts per configuration.
- Changed pipeline/model/prompt/policy fingerprints require a new batch.
- Successful runs return cached output even through the retry command.

There is no autonomous scheduler. After interruption, refresh the run list and resume pending/expired runs. Registered input is durable; registration does not keep a worker alive. Unexpected exceptions become generic stored errors without raw contract/provider details.

Analysis, fields, evidence, findings and completion state commit in one transaction. A failed insert rolls back all normalized output, retaining staging and attempt history. Only the latest staging payload for each run is retained; attempt rows retain execution/error metadata rather than every raw payload.

## Evaluate

```powershell
.venv\Scripts\python -m app.cli evaluate --output data/evaluation.json
```

Evaluation does not write a document database. It verifies PDF hashes, executes the shared engine and reports field comparisons. Definitions and known misses are in `docs/CASE_STUDY.md`.

After deliberate fixture changes, run `scripts/generate_samples.py` then `scripts/build_benchmark.py`, inspect PDFs/answers, and rerun evaluation. Do not derive expected values from extraction merely to raise the score.

For deliberate paid evaluation, configure `OPENAI_API_KEY`, `ENABLE_OPENAI=true`, a compatible `OPENAI_MODEL`, and pass `--mode openai`. This sends fictional text to the provider. Returned token counts are reported; monetary cost stays null. SDK retries can add requests inside an attempt. Interrupted provider calls may be billed again on recovery.

## Retention and backup

Persistent mode retains PDFs, raw text, extraction, results and history until you remove the selected database. There is no automatic retention or per-document delete UI. With server/CLI workers stopped, remove the database and its `-wal`/`-shm` companions to reset that local dataset; preserve anything needed first.

Use SQLite's backup API for a consistent local backup, rather than copying a live WAL file:

```powershell
.venv\Scripts\python -c "import sqlite3; s=sqlite3.connect('data/demo.sqlite3'); d=sqlite3.connect('data/demo-backup.sqlite3'); s.backup(d); d.close(); s.close()"
```

Treat backups as sensitive as the inputs. Automated tests cover a local backup round trip; no production disaster recovery is claimed.

## Deployment boundary

Keep the app on loopback. There is no authentication or multiuser authorization. Public hosting needs access controls, isolated PDF workers, upstream limits, budgets and a data policy. The Dockerfile has not been built in the verified environment. A deliberately deployed container needs a persistent `/app/data` volume to retain its database when removed.
