from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_OPENAI", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("PIPELINE_DB_PATH", str(tmp_path / "pipeline.sqlite3"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


@pytest.fixture
def sample_bytes():
    return (Path(__file__).resolve().parents[1] / "app/samples/complete-agreement.pdf").read_bytes()
