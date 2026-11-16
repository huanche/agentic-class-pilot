"""Structured event logging per docs/logging-standards.md (canonical copy).

student_agent/backend/infrastructure/structured_logging.py is a synced copy of
this module (service name differs) — change both together. Contract vectors
live in platform/backend/tests/logging_vectors/ and are loaded by BOTH test
suites, so any drift fails tests on both sides.
"""

import contextvars
import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone

SERVICE_NAME = "platform"  # the student_agent copy overrides this

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
operation_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("operation_id", default=None)
user_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("user_id", default=None)
course_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("course_id", default=None)
session_key_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("session_key", default=None)

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
# URLs inside exception messages must not carry query strings (tokens etc.)
_URL_QUERY_RE = re.compile(r"(https?://[^?\s]+)\?[^\s]*")
_CONTROL_RE = re.compile(r"[\r\n\t\x00-\x1f]+")


def resolve_request_id(incoming: str | None) -> str:
    """Accept a well-formed external id, else mint one (never trust raw input)."""
    if incoming and (_REQUEST_ID_RE.fullmatch(incoming) or _UUID_RE.fullmatch(incoming)):
        return incoming
    return uuid.uuid4().hex


def sanitize_text(value: object, limit: int = 500) -> str:
    """Single-line, URL-query-stripped, truncated text for exception fields."""
    text = _CONTROL_RE.sub(" ", str(value))
    text = _URL_QUERY_RE.sub(r"\1?…", text)
    return text[:limit]


def level_for_status(status: int) -> str:
    if status >= 500:
        return "error"
    if status in (408, 429):
        return "warning"
    return "info"


def outcome_for_status(status: int) -> str:
    return "failure" if status >= 500 else "success"


_logger = logging.getLogger("structured_events")
_configured = False


def setup_logging() -> None:
    """JSON-lines handler on stdout; uvicorn access log off; LOG_LEVEL gate."""
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(handler)
    _logger.propagate = False
    level = os.environ.get("LOG_LEVEL", "info").upper()
    _logger.setLevel(getattr(logging, level, logging.INFO))
    logging.getLogger("uvicorn.access").disabled = True
    _configured = True


def emit_event(event: str, *, level: str = "info", **fields: object) -> None:
    """One JSON line per event; correlation fields read from contextvars."""
    record: dict[str, object] = {
        "ts": datetime.now(timezone.utc).isoformat(),  # noqa: UP017 — student copy runs on Python 3.10
        "level": level,
        "service": SERVICE_NAME,
        "event": event,
    }
    if (rid := request_id_var.get()) is not None:
        record["request_id"] = rid
    if (oid := operation_id_var.get()) is not None:
        record["operation_id"] = oid
    if (uid := user_id_var.get()) is not None:
        record["user_id"] = uid
    if (cid := course_id_var.get()) is not None:
        record["course_id"] = cid
    if (sk := session_key_var.get()) is not None:
        record["session_key"] = sk
    for key, value in fields.items():
        if value is not None:
            record[key] = value
    _logger.log(getattr(logging, level.upper(), logging.INFO),
                json.dumps(record, ensure_ascii=False, separators=(",", ":")))


def log_request_completed(
    *, method: str, path: str, route: str | None, status: int, duration_ms: int,
) -> None:
    """`http.request.completed` per §2; level maps from status (spec §3)."""
    emit_event(
        "http.request.completed",
        level=level_for_status(status),
        outcome=outcome_for_status(status),
        method=method,
        path=path,
        route=route,
        status_code=status,
        duration_ms=duration_ms,
    )


def log_client_completed(
    *, target_service: str, method: str, path: str, status: int | None, duration_ms: int,
) -> None:
    """`http.client.completed` for outbound service calls (spec §2)."""
    status = status if status is not None else 0
    emit_event(
        "http.client.completed",
        level=level_for_status(status),
        outcome=outcome_for_status(status),
        target_service=target_service,
        method=method,
        path=path,
        status_code=status or None,
        duration_ms=duration_ms,
    )


def log_llm_call(
    *, model: str, duration_ms: int, ok: bool, error_code: str | None = None,
    error_type: str | None = None, retry_count: int | None = None, phase: str | None = None,
) -> None:
    """`llm.call.completed`; retry_count only for OUR explicit retries (spec §4)."""
    detail: dict[str, object] = {"model": model}
    if phase is not None:
        detail["phase"] = phase
    if retry_count is not None:
        detail["retry_count"] = retry_count
    emit_event(
        "llm.call.completed",
        level="info" if ok else "error",
        outcome="success" if ok else "failure",
        detail=detail,
        error_code=error_code,
        error_type=error_type,
        duration_ms=duration_ms,
    )


def log_state_changed(level: str = "info", **fields: object) -> None:
    emit_event("state.changed", level=level, **fields)


class RequestLoggingMiddleware:
    """Pure-ASGI request completion logging (spec §2/§3/§6/§12).

    Outermost middleware: validates/carry the request id, writes it back to
    the response, times the request, and emits `http.request.completed`.
    user_id arrives via contextvar set by the (async) auth dependency — the
    middleware deliberately never parses credentials itself.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        request_id = resolve_request_id(headers.get("x-request-id"))
        token = request_id_var.set(request_id)
        start = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                message.setdefault("headers", [])
                message["headers"] = [
                    *message["headers"],
                    (b"x-request-id", request_id.encode("latin-1")),
                ]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as error:
            duration_ms = int((time.perf_counter() - start) * 1000)
            emit_event(
                "http.request.completed",
                level="error",
                outcome="failure",
                method=scope.get("method", ""),
                path=scope.get("path", ""),
                route=_route_template(scope),
                status_code=500,
                duration_ms=duration_ms,
                error_type=type(error).__name__,
                exception={"message": sanitize_text(error)},
            )
            request_id_var.reset(token)
            raise
        duration_ms = int((time.perf_counter() - start) * 1000)
        status = status_holder["status"]
        method = scope.get("method", "")
        path = scope.get("path", "")
        route = _route_template(scope)
        log_request_completed(
            method=method, path=path, route=route,
            status=status, duration_ms=duration_ms,
        )
        request_id_var.reset(token)


def _route_template(scope) -> str | None:
    route = scope.get("route")
    if route is None:
        return None
    return getattr(route, "path_format", None) or getattr(route, "path", None) or None
