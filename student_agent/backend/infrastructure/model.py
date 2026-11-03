"""Shared model adapter for content preparation, classroom and postclass teaching."""
from __future__ import annotations

import json
import os
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI


def _model(*, timeout_seconds: float = 45, retries: int = 1) -> ChatOpenAI:
    key = os.environ.get("STUDENT_AGENT_API_KEY") or os.environ.get("LLM_API_KEY")
    if not key:
        raise RuntimeError("请配置 STUDENT_AGENT_API_KEY 或 LLM_API_KEY")
    return ChatOpenAI(api_key=key,
                      base_url=os.environ.get("STUDENT_AGENT_BASE_URL") or
                      os.environ.get("LLM_BASE_URL") or "https://api.deepseek.com/v1",
                      model=os.environ.get("STUDENT_AGENT_MODEL") or
                      os.environ.get("LLM_MODEL") or "deepseek-v4-flash",
                      temperature=0.2, timeout=timeout_seconds, max_retries=retries)


def complete(system: str, user: str) -> str:
    result = _model().invoke([SystemMessage(content=system), HumanMessage(content=user)])
    return str(result.content)


def complete_bounded(system: str, user: str, timeout_seconds: float) -> str:
    """Pilot calls consume one bounded attempt; repair is owned by the executor."""
    client = _model(timeout_seconds=timeout_seconds, retries=0)
    result = client.invoke([SystemMessage(content=system), HumanMessage(content=user)])
    return str(result.content)


def json_object(raw: str) -> dict:
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        value = json.loads(clean)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}
