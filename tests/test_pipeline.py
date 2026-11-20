import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.analysis import analyze_document
from app.config import get_settings
from app.errors import AnalysisError
from app.pipeline import DocumentInput, Pipeline, extraction_config
from app.storage import PipelineStore


@pytest.fixture
def store(tmp_path):
    return PipelineStore(tmp_path / "test.sqlite3")


def test_demo_persists_normalized_layers_and_second_batch_is_cached(client):
    first = client.post("/api/pipeline/demo").json()
    assert first["processed"] == 3
    assert first["failed"] == 0
    summary = client.get("/api/pipeline/summary").json()
    assert summary["counts"]["documents"] == 3
    assert summary["counts"]["contract_fields"] == 33
    assert summary["quality"] == {"checks_passed": 1, "needs_review": 2}
    second = client.post("/api/pipeline/demo").json()
    assert second["cached"] == 3
    assert client.get("/api/pipeline/summary").json()["counts"]["attempts"] == 3
    assert [i["run_id"] for i in first["items"]] == [i["run_id"] for i in second["items"]]
    store = PipelineStore(get_settings().pipeline_db_path)
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM accepted_contract_fields").fetchone()[0] == 11
        assert db.execute("SELECT COUNT(*) FROM quality_quarantine").fetchone()[0] == 22
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_stateless_review_does_not_create_pipeline_database(client, sample_bytes):
    path = get_settings().pipeline_db_path
    assert not path.exists()
    assert (
        client.post("/api/analyze", files={"file": ("contract.pdf", sample_bytes)}).status_code
        == 200
    )
    assert not path.exists()


def test_batch_requires_explicit_persistence_and_provider_consent(client, sample_bytes):
    response = client.post(
        "/api/pipeline/batches", files=[("files", ("contract.pdf", sample_bytes))]
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "persistence_consent_required"
    assert not get_settings().pipeline_db_path.exists()
    response = client.post(
        "/api/pipeline/batches",
        files=[("files", ("contract.pdf", sample_bytes))],
        data={"persist_consent": "true", "mode": "openai"},
    )
    assert response.json()["error"]["code"] == "provider_consent_required"


def test_batch_continues_after_bad_pdf_and_duplicate_content_is_reused(client, sample_bytes):
    response = client.post(
        "/api/pipeline/batches",
        files=[
            ("files", ("corrupt.pdf", b"bad pdf")),
            ("files", ("first.pdf", sample_bytes)),
            ("files", ("renamed.pdf", sample_bytes)),
        ],
        data={"persist_consent": "true"},
    )
    assert response.status_code == 200
    batch = response.json()
    assert batch["failed"] == 1
    assert batch["processed"] == 2
    assert batch["cached"] == 1
    assert batch["items"][0]["error_code"] == "invalid_pdf"
    summary = client.get("/api/pipeline/summary").json()
    assert summary["counts"]["documents"] == 2
    assert summary["counts"]["analyses"] == 1
    assert client.get("/api/pipeline/batches/" + batch["batch_id"]).json() == batch


def test_retry_is_bounded_and_failed_jobs_have_attempt_history(client):
    batch = client.post(
        "/api/pipeline/batches",
        files=[("files", ("broken.pdf", b"bad"))],
        data={"persist_consent": "true"},
    ).json()
    run_id = batch["items"][0]["run_id"]
    for _ in range(4):
        assert client.post(f"/api/pipeline/runs/{run_id}/retry").status_code == 200
    lineage = client.get(f"/api/pipeline/runs/{run_id}/lineage").json()
    assert lineage["run"]["attempt_count"] == 3
    assert lineage["run"]["error_code"] == "retry_limit"
    assert len(lineage["attempts"]) == 3
    assert all(a["state"] == "failed" for a in lineage["attempts"])
    assert client.get(f"/api/pipeline/runs/{run_id}/result").status_code == 404


def test_transient_failure_preserves_staging_then_retry_commits_once(
    store, sample_bytes, monkeypatch
):
    import app.pipeline as module

    service = Pipeline(store)
    real = module.analyze_document

    async def fail_after_read(*args, **kwargs):
        from app.models import SourcePage

        kwargs["checkpoint"]([SourcePage(number=1, text="Client: Fictional Inc.")], None)
        raise AnalysisError("ai_timeout", "Simulated temporary timeout.", 504)

    monkeypatch.setattr(module, "analyze_document", fail_after_read)
    batch = asyncio.run(service.batch([DocumentInput("contract.pdf", sample_bytes)]))
    run_id = batch["items"][0]["run_id"]
    assert store.lineage(run_id)["staging"]["pages"]
    assert store.summary()["counts"]["analyses"] == 0
    monkeypatch.setattr(module, "analyze_document", real)
    outcome = asyncio.run(service.process_run(run_id, retry_failed=True))
    assert outcome["run"]["state"] == "succeeded"
    assert outcome["run"]["attempt_count"] == 2
    assert [a["state"] for a in store.lineage(run_id)["attempts"]] == ["failed", "succeeded"]
    assert store.summary()["counts"]["contract_fields"] == 11
    assert store.lineage(run_id)["staging"]["extraction"]["fields"]["party_a"]["value"]


def test_concurrent_registration_and_claim_have_single_owner(store, sample_bytes):
    config = extraction_config("local", False, get_settings())
    with ThreadPoolExecutor(max_workers=6) as pool:
        ids = list(
            pool.map(lambda _: store.register(sample_bytes, "contract.pdf", config), range(12))
        )
        claims = list(pool.map(lambda _: store.claim(ids[0]), range(12)))
    assert len(set(ids)) == 1
    assert sum(token is not None for token, _ in claims) == 1
    assert store.run(ids[0])["attempt_count"] == 1


def test_expired_worker_cannot_commit_after_recovery(store, sample_bytes):
    run_id = store.register(
        sample_bytes, "contract.pdf", extraction_config("local", False, get_settings())
    )
    old_token, _ = store.claim(run_id)
    with store.connection(write=True) as db:
        db.execute("UPDATE runs SET lease_expires=0 WHERE run_id=?", (run_id,))
    new_token, _ = store.claim(run_id)
    artifacts = asyncio.run(analyze_document(sample_bytes, "contract.pdf", "local"))
    with pytest.raises(AnalysisError) as exc:
        store.complete(run_id, old_token, artifacts)
    assert exc.value.code == "lease_lost"
    store.complete(run_id, new_token, artifacts)
    assert store.summary()["counts"]["analyses"] == 1
    assert store.lineage(run_id)["attempts"][0]["error_code"] == "lease_expired"


def test_failed_normalized_write_rolls_back_all_output_tables(store, sample_bytes):
    with store.connection(write=True) as db:
        db.execute(
            "CREATE TRIGGER reject_evidence BEFORE INSERT ON field_evidence BEGIN SELECT RAISE(ABORT, 'simulated disk failure'); END"
        )
    service = Pipeline(store)
    batch = asyncio.run(service.batch([DocumentInput("contract.pdf", sample_bytes)]))
    run_id = batch["items"][0]["run_id"]
    counts = store.summary()["counts"]
    assert counts["analyses"] == counts["contract_fields"] == counts["field_evidence"] == 0
    assert store.run(run_id)["state"] == "failed"
    assert store.lineage(run_id)["staging"]["extraction"] is not None
    with store.connection(write=True) as db:
        db.execute("DROP TRIGGER reject_evidence")
    assert asyncio.run(service.process_run(run_id, True))["run"]["state"] == "succeeded"


def test_identity_changes_with_configuration_not_filename(store, sample_bytes):
    config = extraction_config("local", False, get_settings())
    first = store.register(sample_bytes, "first.pdf", config)
    assert store.register(sample_bytes, "renamed.pdf", config) == first
    changed = {**config, "policy_hash": "new-policy-version"}
    assert store.register(sample_bytes, "first.pdf", changed) != first
    assert store.summary()["counts"]["documents"] == 1
    assert store.summary()["counts"]["runs"] == 2


def test_changed_configuration_is_not_silently_used_for_retry(store, sample_bytes):
    config = {**extraction_config("local", False, get_settings()), "policy_hash": "old-version"}
    run_id = store.register(sample_bytes, "contract.pdf", config)
    assert (
        asyncio.run(Pipeline(store).process_run(run_id))["run"]["error_code"]
        == "pipeline_version_changed"
    )


def test_interrupted_batch_keeps_all_inputs_and_pending_runs(store, sample_bytes, monkeypatch):
    import app.pipeline as module

    real = module.analyze_document

    async def interrupted(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(module, "analyze_document", interrupted)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            Pipeline(store).batch(
                [DocumentInput("first.pdf", sample_bytes), DocumentInput("second.pdf", b"bad pdf")]
            )
        )
    summary = store.summary()
    assert summary["counts"]["documents"] == 2
    assert summary["states"] == {"queued": 1, "running": 1}
    with store.connection(write=True) as db:
        db.execute("UPDATE runs SET lease_expires=0 WHERE state='running'")
    run_id = next(r["run_id"] for r in summary["recent_runs"] if r["state"] == "running")
    monkeypatch.setattr(module, "analyze_document", real)
    assert asyncio.run(Pipeline(store).process_run(run_id))["run"]["state"] == "succeeded"


def test_sqlite_backup_round_trip_preserves_data(store, sample_bytes, tmp_path):
    import sqlite3

    asyncio.run(Pipeline(store).batch([DocumentInput("contract.pdf", sample_bytes)]))
    backup_path = tmp_path / "backup.sqlite3"
    source = sqlite3.connect(store.path)
    destination = sqlite3.connect(backup_path)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    restored = PipelineStore(backup_path)
    assert restored.summary()["counts"] == store.summary()["counts"]
    run_id = restored.summary()["recent_runs"][0]["run_id"]
    assert restored.result(run_id) == store.result(run_id)


def test_lineage_exposes_raw_and_validated_data_without_credentials(client):
    batch = client.post("/api/pipeline/demo").json()
    run_id = batch["items"][0]["run_id"]
    lineage = client.get(f"/api/pipeline/runs/{run_id}/lineage").json()
    assert lineage["staging"]["extraction"]["fields"]["total_value"]["value"] == "72,000.00"
    result = client.get(f"/api/pipeline/runs/{run_id}/result").json()
    assert next(f for f in result["fields"] if f["key"] == "total_value")["value"] == "72000.00"
    rendered = json.dumps(lineage)
    assert "api_key" not in rendered
    assert "lease_token" not in rendered
    assert client.get("/api/pipeline/runs/unknown/lineage").status_code == 404


def test_batch_limits(store, sample_bytes):
    with pytest.raises(AnalysisError) as exc:
        asyncio.run(Pipeline(store).batch([DocumentInput("same.pdf", sample_bytes)] * 11))
    assert exc.value.code == "batch_count"


def test_cli_reports_cache_hits_and_has_no_dependency_on_working_directory(tmp_path):
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "contract.pdf").write_bytes(
        (root / "app/samples/complete-agreement.pdf").read_bytes()
    )
    command = [
        sys.executable,
        "-m",
        "app.cli",
        "batch",
        str(folder),
        "--database",
        str(tmp_path / "cli.sqlite3"),
    ]
    first = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout)["processed"] == 1
    second = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert json.loads(second.stdout)["cached"] == 1
