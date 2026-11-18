"""One protocol for tool arguments, content validation and compatibility text."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

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
        "需要不同事实或能力才能证明的独立目标应分别记录，不用因果或并列连接词将它们重新合为一项。"
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


class LegacyKnowledgePoints(StrictModel):
    """Submit the complete lesson's typed knowledge points; empty means no teachable content."""

    points: Annotated[list[Point], Field(max_length=120)]


def compatibility_text(point: dict) -> str:
    """Derive legacy prose from typed content; this is not a source quote."""
    if "explanation" in point:
        return point["explanation"]
    details = point["details"]
    if point["type"] == "memory":
        parts = [details["statement"], *details["requiredElements"]]
    elif point["type"] == "concept":
        parts = [details["explanation"], *details["understandingPoints"]]
    else:
        parts = [details["capability"], *details["constraints"], *details["successCriteria"]]
    return "\n".join(dict.fromkeys(parts))


SIMPLE_SCHEMA_VERSION = 3


class CoreKnowledgePoint(StrictModel):
    name: Text
    explanation: Text


class submit_knowledge_points(StrictModel):
    """Submit one to three core points using only name and explanation."""

    points: Annotated[list[CoreKnowledgePoint], Field(min_length=1, max_length=3)]
