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
        "每项只记录一个可独立确认的事实；多个独立事实分别放在列表元素中。同一事实的等价表述去重，一次回答可以覆盖多项。")


class ConceptDetails(StrictModel):
    explanation: Text
    understandingPoints: Elements = Field(description=
        "每项是一个可分别确认的理解目标，完整因果关系保留一项，独立事实必须分项。"
        "如‘入队把新结点接在rear之后’与‘链队列无固定容量的队满限制’必须是两个元素，不能用‘因此’或‘同时’合并。"
        "不要另加综合对比条目重新捆绑这些事实，不靠常识新增未教内容。")


class DesignDetails(StrictModel):
    capability: Text
    constraints: Annotated[list[Text], Field(max_length=40)]
    successCriteria: Elements = Field(description=
        "每项记录一个不重复的可检验结果或过程标准；独立结果分项，同一作品可以同时体现多项，不要求拆成多道题。")


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
