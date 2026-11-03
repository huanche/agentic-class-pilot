"""Shared identities, flow names and application failures. No I/O or execution state."""

import json
from uuid import NAMESPACE_URL, uuid5


class SessionError(Exception):
    def __init__(self, status_code: int, detail: str, *, code: str | None = None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.code = code


def identity(kind, *parts):
    return kind + ":" + uuid5(NAMESPACE_URL, json.dumps(parts, ensure_ascii=False, sort_keys=True)).hex


LEGACY_FLOW = "legacy_recall_v3"
DYNAMIC_FLOW = "dynamic_dialogue_v1"

def is_dynamic_flow(session):
    return session.get("flowVersion", LEGACY_FLOW) == DYNAMIC_FLOW
