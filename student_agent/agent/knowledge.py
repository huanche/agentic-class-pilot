"""Extract assessable concepts with source-backed, recoverable validation."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from .graph import _completion, _json_object
from .prompts import KNOWLEDGE_EXTRACTION_PROMPT

CURRICULUM_VERSION = 10
_PUNCTUATION = str.maketrans("，。；：！？（）【】‘’“”", ",.;:!?()[]''\"\"")


@dataclass
class ValidationIssue:
    index: int
    code: str
    reason: str


@dataclass
class ValidatedBatch:
    points: list[dict]
    issues: list[ValidationIssue]


@dataclass
class KnowledgeResult:
    points: list[dict]
    partial: bool = False
    rejected_count: int = 0
    candidate_count: int = 0
    repair_attempted: bool = False


class KnowledgePreparationError(Exception):
    MESSAGES = {
        "configuration": "课堂导师模型配置不可用，请检查密钥、地址和模型名称",
        "authentication": "课堂导师模型认证失败，请检查 API 密钥",
        "timeout": "课堂导师响应超时，请稍后重试",
        "rate_limit": "课堂导师请求频繁，请稍后重试",
        "provider": "课堂导师服务暂不可用，请稍后重试",
        "format": "课堂知识点结果格式异常，请重试整理",
        "evidence": "课堂知识点未能匹配视频原文，请重试整理",
        "no_content": "当前视频没有可供复述的实质知识点，请教师检查视频内容",
        "unexpected": "课堂知识点整理失败，请稍后重试",
    }

    def __init__(self, code: str, stage: str = "extract",
                 candidate_count: int = 0, accepted_count: int = 0,
                 rejected_count: int = 0, issues: list[ValidationIssue] | None = None):
        self.code = code
        self.stage = stage
        self.candidate_count = candidate_count
        self.accepted_count = accepted_count
        self.rejected_count = rejected_count
        self.issues = issues or []
        message = self.MESSAGES[code]
        if code == "evidence" and self.issues:
            issue = self.issues[0]
            reason = issue.reason.split(":")[0]
            detail = {
                "unknown_source": "引用的场景编号无效",
                "empty_quote": "缺少有效原文引用",
                "invalid_reference": "原文引用格式不正确",
                "quote_not_found": "引用内容在视频原文中找不到",
                "title_not_in_evidence": "知识点名称未出现在引用中",
                "evidence_too_short": "引用内容过短，不足以解释知识点",
                "missing evidence": "缺少原文依据",
            }.get(reason)
            if detail:
                message = f"第 {issue.index + 1} 个知识点校验失败：{detail}。请重试整理"
        super().__init__(message)


def _normalized(value: str) -> tuple[str, list[int]]:
    """Normalize typography, keeping offsets and Latin word boundaries."""
    chars, offsets = [], []
    for match in re.finditer(r"\s+|\S", value):
        char = match.group()
        if char.isspace():
            left = value[match.start() - 1:match.start()]
            right = value[match.end():match.end() + 1]
            if not (left and right and left.isascii() and right.isascii()
                    and left.isalnum() and right.isalnum()):
                continue
            char = " "
        elif 0xFF01 <= ord(char) <= 0xFF5E:
            char = chr(ord(char) - 0xFEE0)
        chars.append(char.translate(_PUNCTUATION))
        offsets.append(match.start())
    return "".join(chars), offsets


def _source_span(content: str, quote: str) -> str | None:
    if not quote.strip():
        return None
    if quote in content:
        return quote
    source, offsets = _normalized(content)
    target, _ = _normalized(quote)
    start = source.find(target) if target else -1
    if start < 0:
        return None
    return content[offsets[start]:offsets[start + len(target) - 1] + 1]


def validate_candidates(result: dict, materials: list[dict]) -> ValidatedBatch:
    sources = {item.get("id"): item for item in materials}
    if not isinstance(result, dict) or not isinstance(result.get("points"), list):
        return ValidatedBatch([], [ValidationIssue(-1, "format", "points must be a list")])
    points, issues, seen = [], [], set()
    for index, item in enumerate(result["points"]):
        if not isinstance(item, dict) or not isinstance(item.get("title"), str) or not item["title"].strip():
            issues.append(ValidationIssue(index, "format", "invalid title"))
            continue
        title = item["title"].strip()
        references = item.get("evidence")
        if not isinstance(references, list) or not references:
            issues.append(ValidationIssue(index, "evidence", "missing evidence"))
            continue
        quotes, source_ids = [], []
        reference_issue = None
        for reference_index, reference in enumerate(references):
            if not isinstance(reference, dict):
                reference_issue = f"invalid_reference:{reference_index}"
                break
            source_id = reference.get("sourceId")
            source = sources.get(source_id) if isinstance(source_id, str) else None
            quote = reference.get("quote")
            if not source or source.get("source") != "published-classroom-scene":
                reference_issue = f"unknown_source:{reference_index}"
                break
            if not isinstance(quote, str) or not quote.strip():
                reference_issue = f"empty_quote:{reference_index}"
                break
            exact = _source_span(str(source.get("content") or ""), quote)
            if exact is None:
                reference_issue = f"quote_not_found:{reference_index}"
                break
            quotes.append(exact.strip())
            source_ids.append(source["id"])
        if reference_issue:
            issues.append(ValidationIssue(index, "evidence", reference_issue))
            continue
        normalized_title = _normalized(title)[0]
        normalized_quotes = [_normalized(quote)[0] for quote in quotes]
        if not normalized_title or not any(normalized_title in quote for quote in normalized_quotes):
            issues.append(ValidationIssue(index, "evidence", "title_not_in_evidence"))
            continue
        if not any(len(quote) >= len(normalized_title) + 8 for quote in normalized_quotes):
            issues.append(ValidationIssue(index, "evidence", "evidence_too_short"))
            continue
        if title in seen:
            continue
        seen.add(title)
        content = "\n\n".join(dict.fromkeys(quotes))
        identity = json.dumps([title, sorted(set(source_ids))], ensure_ascii=False)
        points.append({"id": "concept:" + hashlib.sha256(identity.encode()).hexdigest()[:20],
                       "title": title, "content": content, "description": content,
                       "source": "published-classroom-scene", "sourceIds": list(dict.fromkeys(source_ids))})
    return ValidatedBatch(points, issues)


def validated_points(result: dict, materials: list[dict]) -> list[dict]:
    """Compatibility helper for callers that only need accepted points."""
    return validate_candidates(result, materials).points


def _model_error(error: Exception, stage: str) -> KnowledgePreparationError:
    name = type(error).__name__.lower()
    status = getattr(error, "status_code", None)
    if isinstance(error, RuntimeError) and "请配置" in str(error):
        code = "configuration"
    elif status in (401, 403) or "authentication" in name or "permission" in name:
        code = "authentication"
    elif status == 429 or "rate" in name:
        code = "rate_limit"
    elif "timeout" in name:
        code = "timeout"
    elif status in (400, 404) or "config" in name:
        code = "configuration"
    elif (isinstance(status, int) and status >= 500) or "connection" in name:
        code = "provider"
    else:
        code = "unexpected"
    return KnowledgePreparationError(code, stage)


def _complete(prompt: str, payload: dict, stage: str) -> dict:
    try:
        return _json_object(_completion(prompt, json.dumps(payload, ensure_ascii=False)))
    except Exception as error:
        raise _model_error(error, stage) from error


def learning_points(materials: list[dict]) -> KnowledgeResult:
    scenes = [{key: item.get(key) for key in ("id", "source", "title", "content")}
              for item in materials if item.get("source") == "published-classroom-scene"]
    if not scenes:
        raise KnowledgePreparationError("no_content")
    first = _complete(KNOWLEDGE_EXTRACTION_PROMPT, {"materials": scenes}, "extract")
    batch = validate_candidates(first, materials)
    if isinstance(first.get("points"), list) and not first["points"]:
        raise KnowledgePreparationError("no_content")
    if not batch.points:
        code = "format" if any(issue.code == "format" for issue in batch.issues) else "evidence"
        raise KnowledgePreparationError(
            code, "extract",
            len(first.get("points", [])) if isinstance(first.get("points"), list) else 0,
            len(batch.points), len(batch.issues), batch.issues)
    return KnowledgeResult(batch.points, bool(batch.issues), len(batch.issues),
                           len(first.get("points", [])) if isinstance(first.get("points"), list) else 0,
                           False)
