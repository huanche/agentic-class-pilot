"""Stable domain models for the student agent (platform schemaVersion 1).

The teaching state machine depends only on these models — never on raw
platform JSON or teacher-side database shapes. Platform field changes are
absorbed by course_adapter.py alone.
"""
from typing import List, Optional

from pydantic import BaseModel, Field


class PublicationRef(BaseModel):
    id: str
    version: int


class KnowledgeEntry(BaseModel):
    id: str
    title: str
    content: str = ""
    source_name: Optional[str] = None


class KnowledgePackage(BaseModel):
    title: str = ""
    summary: str = ""
    entries: List[KnowledgeEntry] = Field(default_factory=list)


class SceneAction(BaseModel):
    id: str
    type: str = "speech"
    text: Optional[str] = None


class ClassroomScene(BaseModel):
    id: str
    order: int = 1
    title: str = ""
    actions: List[SceneAction] = Field(default_factory=list)


class ClassroomRef(BaseModel):
    id: str
    player_url: str = ""
    playback_token: Optional[str] = None
    scenes: List[ClassroomScene] = Field(default_factory=list)


class KnowledgePoint(BaseModel):
    id: str
    title: str
    expected_concepts: List[str] = Field(default_factory=list)
    misconceptions: List[str] = Field(default_factory=list)


class EvaluationContract(BaseModel):
    """Course-level assessment contract. `is_default=True` marks the generic
    semantic fallback used when the published package carries no rubric."""
    knowledge_points: List[KnowledgePoint] = Field(default_factory=list)
    completion_rule: str = "student-mentions-core-concept"
    is_default: bool = True
    source: str = "default-semantic"


class Segment(BaseModel):
    id: str
    title: str
    order: int = 1
    source_scene_id: Optional[str] = None
    content: str = ""
    completion_rule: str = "scene-completed"


class Lesson(BaseModel):
    id: str
    title: str
    order: int = 1
    segments: List[Segment] = Field(default_factory=list)
    classroom: Optional[ClassroomRef] = None


class CourseLearningContext(BaseModel):
    """Versioned learning context resolved from a verified launch token."""
    schema_version: int = 1
    user_id: str
    course_id: str
    course_title: str
    publication: PublicationRef
    knowledge_package: KnowledgePackage
    lessons: List[Lesson] = Field(default_factory=list)
    classroom: Optional[ClassroomRef] = None
    evaluation: EvaluationContract = Field(default_factory=EvaluationContract)

    class Config:
        extra = "ignore"  # forward-compatible with new optional platform fields
