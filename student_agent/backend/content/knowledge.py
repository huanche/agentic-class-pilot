"""Typed extraction and structural repair within one create_agent invocation."""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from time import monotonic

from langchain.agents import create_agent
from langchain.agents.middleware import after_model, wrap_model_call
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import ValidationError

from backend.infrastructure import model
from backend.content.knowledge_schema import compatibility_text, submit_knowledge_points
from backend.content.prompts import KNOWLEDGE_EXTRACTION_PROMPT

# Teaching/session compatibility is independent of the extraction compiler version.
# Do not upgrade existing students' curricula just because extraction changed.
CURRICULUM_VERSION = 10
EXTRACTION_VERSION = 2
MAX_MODEL_CALLS = 3
TOTAL_TIMEOUT_SECONDS = 90
log = logging.getLogger(__name__)


@dataclass
class ValidationIssue:
    index: int
    code: str
    reason: str


@dataclass
class KnowledgeResult:
    points: list[dict]
    partial: bool = False
    rejected_count: int = 0
    candidate_count: int = 0
    repair_attempted: bool = False
    model_calls: int = 0
    duplicate_count: int = 0


class KnowledgePreparationError(Exception):
    MESSAGES = {
        "configuration": "课堂导师模型配置不可用，请检查密钥、地址和模型名称",
        "authentication": "课堂导师模型认证失败，请检查 API 密钥",
        "timeout": "课堂导师响应超时，请稍后重试",
        "rate_limit": "课堂导师请求频繁，请稍后重试",
        "provider": "课堂导师服务暂不可用，请稍后重试",
        "format": "课堂知识点结构在有限修正后仍不符合要求，请重试整理",
        "evidence": "课堂知识点未能匹配视频原文，请重试整理",  # legacy errors
        "no_content": "当前视频没有可供整理的实质知识点，请教师检查视频内容",
        "unexpected": "课堂知识点整理失败，请稍后重试",
    }

    def __init__(self, code: str, stage: str = "extract",
                 candidate_count: int = 0, accepted_count: int = 0,
                 rejected_count: int = 0, issues: list[ValidationIssue] | None = None,
                 *, model_calls: int = 0, draft=None):
        self.code, self.stage = code, stage
        self.candidate_count, self.accepted_count = candidate_count, accepted_count
        self.rejected_count, self.issues = rejected_count, issues or []
        self.model_calls, self.draft = model_calls, draft
        super().__init__(self.MESSAGES[code])


def _model_error(error: Exception) -> KnowledgePreparationError:
    name = type(error).__name__.lower()
    status = getattr(error, "status_code", None)
    if isinstance(error, RuntimeError) and "请配置" in str(error):
        code = "configuration"
    elif status in (401, 403) or "authentication" in name or "permission" in name:
        code = "authentication"
    elif status == 429 or "rate" in name:
        code = "rate_limit"
    elif isinstance(error, TimeoutError) or "timeout" in name:
        code = "timeout"
    elif status in (400, 404) or "config" in name:
        code = "configuration"
    elif (isinstance(status, int) and status >= 500) or "connection" in name:
        code = "provider"
    else:
        code = "unexpected"
    return KnowledgePreparationError(code)


def _canonical(value):
    """Only trim edges/normalize newlines; preserve code, punctuation and list order."""
    if isinstance(value, str):
        return value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in value.items()}
    return value


def compile_points(submission: submit_knowledge_points, *, scope: tuple[str, str] | None = None) -> list[dict]:
    """Merge exact duplicates and derive legacy text before assigning identities."""
    points, seen = [], set()
    for candidate in submission.points:
        data = _canonical(candidate.model_dump())
        key = json.dumps(data, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        text = compatibility_text(data)
        identity = json.dumps([scope, data], ensure_ascii=False, sort_keys=True)
        points.append({"id": "knowledge:" + hashlib.sha256(identity.encode()).hexdigest()[:20],
                       **data, "content": text, "description": text})
    return points


def learning_points(materials: list[dict], course_id: str | None = None, lesson_id: str | None = None) -> KnowledgeResult:
    if (course_id is None) != (lesson_id is None) or (course_id is not None and (
            not str(course_id).strip() or not str(lesson_id).strip())):
        raise KnowledgePreparationError("configuration", stage="binding")
    scenes = [{key: item.get(key) for key in ("id", "source", "title", "content")}
              for item in materials if item.get("source") == "published-classroom-scene"
              and str(item.get("content") or "").strip()]
    if not scenes:
        raise KnowledgePreparationError("no_content")
    deadline = monotonic() + TOTAL_TIMEOUT_SECONDS
    calls, draft, issues = 0, None, []

    def failure(code):
        return KnowledgePreparationError(code, issues=issues, model_calls=calls, draft=draft)

    @wrap_model_call
    def bounded_call(request, handler):
        nonlocal calls, draft
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise failure("timeout")
        if calls >= MAX_MODEL_CALLS:
            raise failure("format")
        calls += 1
        response = handler(request.override(model_settings={
            **request.model_settings, "timeout": min(45, remaining),
            "parallel_tool_calls": False,
        }))
        if monotonic() >= deadline:
            raise failure("timeout")
        # ToolStrategy appends a ToolMessage after validating a structured call.
        message = next(m for m in reversed(response.result) if isinstance(m, AIMessage))
        draft = [{"name": call.get("name"), "args": call.get("args")}
                 for call in [*message.tool_calls, *message.invalid_tool_calls]] or message.content
        log.info("knowledge_extraction_submission attempt=%d tool_calls=%d", calls, len(message.tool_calls))
        return response

    def structure_feedback(error):
        # ToolStrategy sends this as a ToolMessage and retries in the same context.
        source = getattr(error, "source", None)
        validation = source if isinstance(source, ValidationError) else getattr(source, "__cause__", None)
        if isinstance(validation, ValidationError):
            for detail in validation.errors(include_input=False, include_url=False):
                loc = detail["loc"]
                index = loc[1] if len(loc) > 1 and loc[0] == "points" and isinstance(loc[1], int) else -1
                issues.append(ValidationIssue(index, "format", ".".join(map(str, loc)) + ": " + detail["msg"]))
        else:
            issues.append(ValidationIssue(-1, "format", type(error).__name__))
        return f"结构校验失败：{error}\n请按工具参数结构修正并重新提交完整列表，不要改为普通文本。"

    @after_model(can_jump_to=["model"])
    def require_submission(state, runtime):
        message = next(m for m in reversed(state["messages"]) if isinstance(m, AIMessage))
        invalid = [*message.invalid_tool_calls,
                   *(call for call in message.tool_calls if call["name"] != "submit_knowledge_points")]
        if invalid:
            issues.append(ValidationIssue(-1, "format", "invalid_submission_tool_call"))
            return {"messages": [ToolMessage(content="工具名或参数 JSON 无效，请使用 submit_knowledge_points 重新提交。",
                                             tool_call_id=call["id"]) for call in invalid if call.get("id")],
                    "structured_response": None, "jump_to": "model"}
        if not message.tool_calls:
            issues.append(ValidationIssue(-1, "format", "missing_or_malformed_tool_call"))
            return {"messages": [HumanMessage(content=
                    "尚未收到有效的工具提交。请调用 submit_knowledge_points 提交完整 points，不能只回复文本。")],
                    "jump_to": "model"}
        return None

    try:
        agent = create_agent(model.extraction_model(), system_prompt=KNOWLEDGE_EXTRACTION_PROMPT,
                             response_format=ToolStrategy(submit_knowledge_points, handle_errors=structure_feedback),
                             middleware=[bounded_call, require_submission])
        state = agent.invoke({"messages": [HumanMessage(content=json.dumps({"materials": scenes}, ensure_ascii=False))]},
                             config={"recursion_limit": 30})
        submitted = state.get("structured_response")
        if not isinstance(submitted, submit_knowledge_points):
            raise failure("format")
        if not submitted.points:
            raise failure("no_content")
        scope = (str(course_id), str(lesson_id)) if course_id is not None else None
        points = compile_points(submitted, scope=scope)
        return KnowledgeResult(points, candidate_count=len(submitted.points), repair_attempted=calls > 1,
                               model_calls=calls, duplicate_count=len(submitted.points) - len(points))
    except KnowledgePreparationError:
        raise
    except Exception as error:
        mapped = _model_error(error)
        mapped.model_calls, mapped.draft, mapped.issues = calls, draft, issues
        raise mapped from error
