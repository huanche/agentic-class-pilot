"""One protocol for tool arguments, content validation and compatibility text."""
from __future__ import annotations

import json

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

SCHEMA_VERSION = 2
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=6000)]
Elements = Annotated[list[Text], Field(min_length=1, max_length=40)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class MemoryDetails(StrictModel):
    statement: Text
    requiredElements: Elements = Field(description=
        "每项记录一个判断该知识点是否掌握时必须确认的事实。"
        "术语的等价表述和同一事实的例子不另设条目。")


class ConceptDetails(StrictModel):
    explanation: Text
    understandingPoints: Elements = Field(description=
        "每项记录一个必须能说明的关系、原因或过程。"
        "保留完整因果和条件关系；独立的必要目标分别记录；等价结论和样例应用不另设条目。")


class DesignDetails(StrictModel):
    capability: Text = Field(description=
        "用一句话概括需要构造的产出和体现的可复用能力。无需复述约束或逐项列出完成标准。")
    constraints: Annotated[list[Text], Field(max_length=40)] = Field(description=
        "只列材料明确规定且适用于该任务的条件与限制。示范做法只有在材料明确指定时才成为约束。")
    successCriteria: Elements = Field(description=
        "每项记录一个从学生产出或操作过程可直接检查的必要完成条件。"
        "独立结果分别记录，不重复登记约束、任务概述或示范细节。")


class MemoryPoint(StrictModel):
    title: Text
    type: Literal["memory"]
    details: MemoryDetails


class ConceptPoint(StrictModel):
    title: Text
    type: Literal["concept"]
    details: ConceptDetails


class DesignPoint(StrictModel):
    title: Text
    type: Literal["design"]
    details: DesignDetails


Point = Annotated[MemoryPoint | ConceptPoint | DesignPoint, Field(discriminator="type")]


class StoredKnowledgePoints(StrictModel):
    """Validate stored typed content independently of current extraction limits."""

    points: Annotated[list[Point], Field(max_length=120)]


def canonical_point(value):
    """Only trim edges/normalize newlines; preserve code, punctuation and list order."""
    if isinstance(value, str):
        return value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if isinstance(value, list):
        return [canonical_point(item) for item in value]
    if isinstance(value, dict):
        return {key: canonical_point(item) for key, item in value.items()}
    return value


class submit_knowledge_points(StoredKnowledgePoints):
    """Submit 3 to 8 knowledge points for a new extraction."""

    points: Annotated[list[Point], Field(min_length=3, max_length=8)]

    @model_validator(mode="after")
    def require_distinct_points(self):
        unique = {json.dumps(canonical_point(point.model_dump()), ensure_ascii=False, sort_keys=True)
                  for point in self.points}
        if len(unique) < 3:
            raise ValueError("After deduplication, provide at least 3 distinct knowledge points (maximum 8). "
                             "Resubmit the complete list using only taught content; do not invent or duplicate points.")
        return self


def compatibility_text(point: dict) -> str:
    """Derive legacy prose from typed content; this is not a source quote."""
    details = point["details"]
    if point["type"] == "memory":
        parts = [details["statement"], *details["requiredElements"]]
    elif point["type"] == "concept":
        parts = [details["explanation"], *details["understandingPoints"]]
    else:
        parts = [details["capability"], *details["constraints"], *details["successCriteria"]]
    return "\n".join(dict.fromkeys(parts))
