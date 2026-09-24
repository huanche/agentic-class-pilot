"""Launch token parsing and lifecycle.

The token is the only trusted identity source for a student session; browser
parameters never override it. Signature verification stays local (shared
STUDENT_SERVICE_KEY); enrollment/publication re-validation happens on the
platform when the learning context is fetched.
"""
import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict

from .config import student_service_key


class LaunchTokenError(ValueError):
    """Malformed, tampered-with, or expired launch token."""


def _signature(payload_json: str, key: str) -> str:
    return hmac.new(key.encode(), payload_json.encode(), hashlib.sha256).hexdigest()


def verify_launch_token(token: str) -> Dict[str, Any]:
    """Validate signature + expiry and return the platform payload."""
    key = student_service_key()
    if not key:
        raise LaunchTokenError("launch token 入口未配置（正式模式 fail closed）")
    encoded, _, signature = token.partition(".")
    if not signature:
        raise LaunchTokenError("令牌格式无效")
    padded = encoded + "=" * (-len(encoded) % 4)
    try:
        payload_json = base64.urlsafe_b64decode(padded).decode("utf-8")
        payload = json.loads(payload_json)
    except (ValueError, json.JSONDecodeError) as error:
        raise LaunchTokenError("令牌格式无效") from error
    if not hmac.compare_digest(signature, _signature(payload_json, key)):
        raise LaunchTokenError("令牌签名不匹配")
    if int(payload.get("exp", 0)) < time.time():
        raise LaunchTokenError("令牌已过期，请从平台重新进入")
    for field in ("uid", "cid", "pub"):
        if not payload.get(field):
            raise LaunchTokenError(f"令牌缺少字段：{field}")
    return payload


def launch_identity(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalized trusted identity bound into the session record."""
    publication = payload.get("pub") or {}
    return {
        "userId": payload["uid"],
        "courseId": payload["cid"],
        "classroomId": payload.get("rid"),
        "publicationId": publication.get("publicationId"),
        "publicationVersion": publication.get("version"),
        "launchedAt": int(time.time()),
    }
