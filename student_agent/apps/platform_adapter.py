"""Platform adaptation layer for the student agent (see PLATFORM-INTEGRATION.md).

Trusted launch entry: the platform issues a short-lived HMAC-signed launch
token (see platform backend/app/api/routes/student_bridge.py). This module
verifies it locally with the shared STUDENT_SERVICE_KEY and extracts the
authoritative learning context:

- user_id    — the platform student identity; caller-supplied student ids are
               ignored whenever a launch token is present
- course_id / classroom_id — course and published classroom to learn
- publication — {publicationId, version}; the session pins this version so a
               later teacher re-publish cannot change an ongoing lesson

The key is provided via STUDENT_SERVICE_KEY and must match the platform
configuration. Without it, launch-token entry is disabled (fail closed).
"""
import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any


class LaunchTokenError(ValueError):
    """Raised when a launch token is malformed, tampered with, or expired."""


def student_service_key() -> str:
    return os.environ.get("STUDENT_SERVICE_KEY", "").strip()


def _signature(payload_json: str, key: str) -> str:
    return hmac.new(key.encode(), payload_json.encode(), hashlib.sha256).hexdigest()


def verify_launch_token(token: str) -> dict[str, Any]:
    """Validate signature + expiry and return the platform context payload."""
    key = student_service_key()
    if not key:
        raise LaunchTokenError("launch token entry is not configured on this service")
    encoded, _, signature = token.partition(".")
    if not signature:
        raise LaunchTokenError("malformed launch token")
    padded = encoded + "=" * (-len(encoded) % 4)
    try:
        payload_json = base64.urlsafe_b64decode(padded).decode()
        payload = json.loads(payload_json)
    except (ValueError, json.JSONDecodeError) as error:
        raise LaunchTokenError("malformed launch token") from error
    if not hmac.compare_digest(signature, _signature(payload_json, key)):
        raise LaunchTokenError("launch token signature mismatch")
    if int(payload.get("exp", 0)) < time.time():
        raise LaunchTokenError("launch token expired")
    for required in ("uid", "cid", "rid", "pub"):
        if not payload.get(required):
            raise LaunchTokenError(f"launch token missing field: {required}")
    return payload


def launch_context(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalized context stored alongside the session (version pinned)."""
    publication = payload.get("pub") or {}
    return {
        "userId": payload["uid"],
        "courseId": payload["cid"],
        "classroomId": payload["rid"],
        "publicationId": publication.get("publicationId"),
        "publicationVersion": publication.get("version"),
        "launchedAt": int(time.time()),
    }
