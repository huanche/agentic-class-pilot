"""Pinned dynamic policy and pure state inspection; no model execution."""
from __future__ import annotations
from copy import deepcopy

class DynamicError(ValueError):
    code = "INVALID_DECISION"


POLICY = {"version": "dynamic-pilot-v1", "maxTurns": 12, "maxTaskTurns": 4,
          "turnTimeoutSeconds": 90, "modelCallSeconds": 25, "minimumIndependentResponses": 1}


def read_state(session):
    state = deepcopy(session.get("teachingState") or {"stage": "opening", "task": None, "turns": 0,
        "taskTurns": 0, "taskOrdinal": 0, "coveredTopics": [], "returnPoint": None,
        "episodeKind": "classroom", "activityStatus": "active"})
    if session.get("teachingPolicy") != POLICY:
        # Keep v1 executable after disabling the allowlist; never reinterpret unknown policies.
        raise DynamicError("Unsupported pinned teaching policy")
    task = state["task"]
    if task:
        canonical = next((t for t in (session.get("learningRecords") or {}).get("tasks", [])
                          if t["taskId"] == task["taskId"]), None)
        if canonical and any(task.get(k) != canonical.get(k) for k in
                ("type", "topicId", "contentId", "purpose", "sourceRefs", "question", "criteria")):
            raise DynamicError("Teaching task differs from the committed task definition")
    return state
