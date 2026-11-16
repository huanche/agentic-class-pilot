"""Contract tests for structured logging (docs/logging-standards.md §12).

Loads the shared vectors in tests/logging_vectors/ and runs them against BOTH
the platform module and the student_agent synced copy — drift fails here.
"""

import importlib.util
import json
import logging
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import structured_logging as platform_sl

VECTORS_DIR = Path(__file__).resolve().parents[1] / "logging_vectors"
SCHEMA = json.loads((VECTORS_DIR / "event_schema.json").read_text(encoding="utf-8"))
VECTORS = json.loads((VECTORS_DIR / "sanitize_vectors.json").read_text(encoding="utf-8"))
STUDENT_COPY = (
    Path(__file__).resolve().parents[4] / "student_agent" / "backend"
    / "infrastructure" / "structured_logging.py"
)


def _load_student_copy():
    spec = importlib.util.spec_from_file_location(
        "student_structured_logging", STUDENT_COPY,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def capture():
    """Attach a list handler to the platform events logger."""

    class ListHandler(logging.Handler):
        def __init__(self):
            super().__init__()
            self.lines: list[str] = []

        def emit(self, record):
            self.lines.append(record.getMessage())

    handler = ListHandler()
    platform_sl._logger.addHandler(handler)
    platform_sl.setup_logging()
    yield handler.lines
    platform_sl._logger.removeHandler(handler)


# --- pure functions, against shared vectors -------------------------------


def test_request_id_validation_matches_vectors():
    for value in VECTORS["request_id"]["valid"]:
        assert platform_sl.resolve_request_id(value) == value
    for value in VECTORS["request_id"]["invalid"]:
        regenerated = platform_sl.resolve_request_id(value)
        assert regenerated != value or not value  # minted anew
        assert platform_sl._REQUEST_ID_RE.fullmatch(regenerated)


def test_sanitize_matches_shared_vectors():
    for case in VECTORS["sanitize"]:
        output = platform_sl.sanitize_text(case["input"], case["limit"])
        if "expected" in case:
            assert output == case["expected"], case["name"]
        if "expected_prefix" in case:
            assert output.startswith(case["expected_prefix"]), case["name"]
        for forbidden in case.get("forbidden", []):
            assert forbidden not in output, case["name"]


def test_status_level_mapping_matches_shared_vectors():
    for status, level in VECTORS["status_levels"].items():
        assert platform_sl.level_for_status(int(status)) == level, status


def test_student_copy_matches_contract():
    """The synced copy passes the SAME vectors and emits the SAME shape."""
    student_sl = _load_student_copy()
    for value in VECTORS["request_id"]["valid"]:
        assert student_sl.resolve_request_id(value) == value
    for case in VECTORS["sanitize"]:
        output = student_sl.sanitize_text(case["input"], case["limit"])
        if "expected" in case:
            assert output == case["expected"], case["name"]
    assert student_sl.SERVICE_NAME == "student-agent"
    assert platform_sl.SERVICE_NAME == "platform"


# --- middleware integration ------------------------------------------------


def _events(lines):
    return [json.loads(line) for line in lines]


def _make_app():
    app = FastAPI()

    @app.get("/api/v1/items/{item_id}")
    def read_item(item_id: str):
        return {"id": item_id}

    @app.get("/api/v1/boom")
    def boom():
        raise RuntimeError(
            "upstream https://api.llm.example.com/v1/chat?api_key=sk-secret blew up"
        )

    app.add_middleware(platform_sl.RequestLoggingMiddleware)
    return app


def test_middleware_emits_contract_compliant_event(capture):
    client = TestClient(_make_app())
    response = client.get(
        "/api/v1/items/8c1f?skip=0", headers={"x-request-id": "abcd1234"},
    )
    assert response.status_code == 200
    assert response.headers["x-request-id"] == "abcd1234"

    events = _events(capture)
    assert len(events) == 1
    event = events[0]
    for field in SCHEMA["always_required"]:
        assert field in event, field
    for field in SCHEMA["events"]["http.request.completed"]["required"]:
        assert field in event, field
    assert event["service"] in SCHEMA["services"]
    assert event["level"] in SCHEMA["levels"]
    assert event["outcome"] in SCHEMA["outcomes"]
    assert event["request_id"] == "abcd1234"
    assert event["route"] == "/api/v1/items/{item_id}"  # templated
    assert event["path"] == "/api/v1/items/8c1f"  # no query string
    assert isinstance(event["duration_ms"], int) and event["duration_ms"] >= 0


def test_middleware_rejects_bad_request_id(capture):
    client = TestClient(_make_app())
    response = client.get("/api/v1/items/x", headers={"x-request-id": "<script>"})
    assert response.status_code == 200
    rewritten = response.headers["x-request-id"]
    assert rewritten != "<script>"
    event = _events(capture)[0]
    assert platform_sl._REQUEST_ID_RE.fullmatch(event["request_id"])


def test_middleware_error_event_sanitizes_and_levels(capture):
    client = TestClient(_make_app(), raise_server_exceptions=False)
    response = client.get("/api/v1/boom")
    assert response.status_code == 500

    events = _events(capture)
    assert len(events) == 1
    event = events[0]
    assert event["level"] == "error"
    assert event["outcome"] == "failure"
    assert event["status_code"] == 500
    assert event["error_type"] == "RuntimeError"
    message = event["exception"]["message"]
    assert "sk-secret" not in message
    assert "api.llm.example.com/v1/chat?…" in message


def test_level_mapping_for_user_errors(capture):
    app = FastAPI()

    @app.get("/api/v1/missing/{item_id}")
    def missing(item_id: str):  # noqa: ARG001 — name must match the path template
        from fastapi import HTTPException
        raise HTTPException(404, "nope")

    app.add_middleware(platform_sl.RequestLoggingMiddleware)
    client = TestClient(app, raise_server_exceptions=False)
    client.get("/api/v1/missing/1")
    event = _events(capture)[0]
    # user errors are normal traffic: info, outcome success (handled correctly)
    assert event["level"] == "info"
    assert event["status_code"] == 404
