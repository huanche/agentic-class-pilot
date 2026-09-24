"""Tests for the ported LLM model factory (registry + service).

The service is exercised with fake models (plain objects exposing an async
``ainvoke``) so no network calls happen. OpenAI errors are constructed with
throwaway httpx request/response objects, matching what the vendored retry
logic detects.
"""

import asyncio
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from openai import APIError, RateLimitError
from tenacity import wait_fixed

from app.core.config import settings
from app.services.llm.registry import LLMRegistry
from app.services.llm.service import LLMService


class FakeModel:
    """Minimal async chat model yielding queued outcomes.

    When the outcome queue is down to its last element it is repeated on every
    further call, so a model configured with a single error fails all retry
    attempts without the test pre-counting them.
    """

    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    async def ainvoke(self, messages: Any, **kwargs: Any) -> Any:
        del kwargs
        self.calls += 1
        outcome = self._outcomes.pop(0) if len(self._outcomes) > 1 else self._outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class SlowModel:
    """Never resolves within any sane timeout budget."""

    async def ainvoke(self, messages: Any, **kwargs: Any) -> Any:
        del messages, kwargs
        await asyncio.sleep(5)


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.test/v1/chat/completions")


def _rate_limit_error() -> RateLimitError:
    return RateLimitError(
        "rate limited", response=httpx.Response(429, request=_request()), body=None
    )


def _api_error() -> APIError:
    return APIError("boom", _request(), body=None)


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    # tenacity's wait is baked into the decorator at import time; retarget the
    # shared Retrying object at a zero wait so retry tests stay fast.
    monkeypatch.setattr(LLMService._invoke_with_retry.retry, "wait", wait_fixed(0))


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_default_entry_matches_settings() -> None:
    model = LLMRegistry.get(settings.LLM_MODEL)
    assert model is LLMRegistry.LLMS[0]["llm"]
    assert model.model_name == settings.LLM_MODEL
    assert model.openai_api_base == settings.LLM_BASE_URL


def test_registry_unknown_name_raises() -> None:
    with pytest.raises(ValueError, match="not found in registry"):
        LLMRegistry.get("no-such-model")


def test_registry_get_with_kwargs_returns_fresh_instance() -> None:
    shared = LLMRegistry.get(settings.LLM_MODEL)
    one_off = LLMRegistry.get(settings.LLM_MODEL, temperature=0.9)
    assert one_off is not shared
    assert one_off.model_name == settings.LLM_MODEL
    assert one_off.temperature == 0.9


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def test_service_call_success_default_path() -> None:
    svc = LLMService()
    fake = FakeModel([AIMessage(content="ok")])
    svc._llm = fake
    result = asyncio.run(svc.call([HumanMessage(content="hi")]))
    assert result.content == "ok"
    assert fake.calls == 1


def test_invoke_with_retry_recovers_after_rate_limit() -> None:
    svc = LLMService()
    fake = FakeModel([_rate_limit_error(), AIMessage(content="recovered")])
    result = asyncio.run(
        svc._invoke_with_retry(fake, [HumanMessage(content="hi")])
    )
    assert result.content == "recovered"
    assert fake.calls == 2


def test_service_falls_back_to_next_model() -> None:
    failing = FakeModel([_api_error()])
    recovering = FakeModel([AIMessage(content="from-b")])
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            LLMRegistry,
            "LLMS",
            [
                {"name": "fake-a", "llm": failing},
                {"name": "fake-b", "llm": recovering},
            ],
        )
        # DEFAULT_LLM_MODEL ("deepseek-v4-flash") is not in the fake registry,
        # so init falls back to entry 0 — which is what this test wants.
        svc = LLMService()
        result = asyncio.run(svc.call([HumanMessage(content="hi")]))
    assert result.content == "from-b"
    assert failing.calls == settings.MAX_LLM_CALL_RETRIES
    assert recovering.calls == 1
    # default path keeps the switched model for subsequent calls
    assert svc.get_llm() is recovering


def test_service_all_models_failed_raises_runtime_error() -> None:
    failing_a = FakeModel([_api_error()])
    failing_b = FakeModel([_api_error()])
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            LLMRegistry,
            "LLMS",
            [
                {"name": "fake-a", "llm": failing_a},
                {"name": "fake-b", "llm": failing_b},
            ],
        )
        svc = LLMService()
        with pytest.raises(RuntimeError, match="failed to get response"):
            asyncio.run(svc.call([HumanMessage(content="hi")]))
    assert failing_a.calls == settings.MAX_LLM_CALL_RETRIES
    assert failing_b.calls == settings.MAX_LLM_CALL_RETRIES


def test_service_total_timeout_raises_runtime_error() -> None:
    svc = LLMService()
    svc._llm = SlowModel()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "LLM_TOTAL_TIMEOUT", 0.05)
        with pytest.raises(RuntimeError, match="timed out"):
            asyncio.run(svc.call([HumanMessage(content="hi")]))
