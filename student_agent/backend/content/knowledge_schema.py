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
    requiredElements: Elements


class ConceptDetails(StrictModel):
    explanation: Text
    understandingPoints: Elements


class DesignDetails(StrictModel):
    capability: Text
    constraints: Annotated[list[Text], Field(max_length=40)]
    successCriteria: Elements


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


class submit_knowledge_points(StrictModel):
    """Submit the complete lesson's typed knowledge points; empty means no teachable content."""

    points: Annotated[list[Point], Field(max_length=120)]


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
