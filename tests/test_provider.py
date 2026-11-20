import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APITimeoutError, AuthenticationError, RateLimitError

from app.config import Settings
from app.errors import AnalysisError
from app.extractors import extract_local, extract_openai
from app.models import SourcePage


def configured():
    return Settings(enable_openai=True, openai_api_key="test-key-never-real", _env_file=None)


def mock_client(monkeypatch, parse):
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.responses.parse = parse
    monkeypatch.setattr("app.extractors.AsyncOpenAI", lambda **kwargs: client)


def test_structured_provider_success(monkeypatch):
    pages = [SourcePage(number=1, text="Client: Fictional Inc.")]
    extracted = extract_local(pages)
    parse = AsyncMock(return_value=SimpleNamespace(output_parsed=extracted))
    mock_client(monkeypatch, parse)
    result = asyncio.run(extract_openai(pages, configured()))
    assert result.fields.party_b.value == "Fictional Inc."
    kwargs = parse.call_args.kwargs
    assert kwargs["store"] is False
    assert "[PAGE 1]" in kwargs["input"][0]["content"]
    assert "untrusted" in kwargs["instructions"]


def test_provider_refusal_has_no_fake_result(monkeypatch):
    mock_client(monkeypatch, AsyncMock(return_value=SimpleNamespace(output_parsed=None)))
    with pytest.raises(AnalysisError, match="declined") as exc:
        asyncio.run(extract_openai([SourcePage(number=1, text="Some text")], configured()))
    assert exc.value.code == "ai_no_result"


def test_reported_token_usage_is_preserved_without_invented_cost(monkeypatch):
    pages = [SourcePage(number=1, text="Client: Fictional Inc.")]
    parse = AsyncMock(
        return_value=SimpleNamespace(
            output_parsed=extract_local(pages),
            usage=SimpleNamespace(
                input_tokens=123,
                output_tokens=45,
                input_tokens_details=SimpleNamespace(cached_tokens=20),
            ),
        )
    )
    mock_client(monkeypatch, parse)
    usage = {}
    asyncio.run(extract_openai(pages, configured(), usage))
    assert usage == {"input_tokens": 123, "output_tokens": 45, "cached_input_tokens": 20}


@pytest.mark.parametrize(
    "kind,code",
    [
        ("timeout", "ai_timeout"),
        ("quota", "ai_rate_limited"),
        ("auth", "ai_authentication"),
        ("schema", "ai_invalid_response"),
    ],
)
def test_provider_failures_are_actionable(monkeypatch, kind, code):
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(429 if kind == "quota" else 401, request=request)
    errors = {
        "timeout": APITimeoutError(request=request),
        "quota": RateLimitError(
            "Provider quota details must stay private", response=response, body=None
        ),
        "auth": AuthenticationError("Secret server details", response=response, body=None),
        "schema": ValueError("Bad schema"),
    }
    mock_client(monkeypatch, AsyncMock(side_effect=errors[kind]))
    with pytest.raises(AnalysisError) as exc:
        asyncio.run(extract_openai([SourcePage(number=1, text="Some text")], configured()))
    assert exc.value.code == code
    assert "Secret" not in exc.value.message
