"""Prepare shared lesson content without owning job state or database writes."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from backend.content import lesson_content
from backend.content.context import classroom_materials
from backend.content.knowledge import EXTRACTION_VERSION, learning_points
from backend.content.knowledge_schema import submit_knowledge_points
from backend.content.prompts import KNOWLEDGE_EXTRACTION_PROMPT


EXTRACTOR_HASH = hashlib.sha256(
    json.dumps([EXTRACTION_VERSION, KNOWLEDGE_EXTRACTION_PROMPT,
                submit_knowledge_points.model_json_schema()], sort_keys=True).encode()
).hexdigest()


def compiler_version(extractor):
    return "lesson-content-v1:" + extractor


def build_content(course, lesson, revision, compiler, scenes, points, coverage):
    return lesson_content.build(course, lesson, revision, compiler_version(compiler), points,
                                classroom_materials(scenes), scenes=scenes, coverage=coverage)


@dataclass
class PreparedContent:
    # Keep the extraction result separate from the content package's filtered points.
    points: list[dict]
    coverage: dict
    body: dict


def prepare_content(course, lesson, revision, compiler, scenes, *, extract=learning_points):
    """Return a candidate package using the compiler fixed when the job was claimed.

    The extraction callable is an internal seam for the worker's existing model
    replacement; callers outside preparation need no model or transport settings.
    """
    result = extract(classroom_materials(scenes), course, lesson)
    coverage = {"partial": result.partial, "acceptedCount": len(result.points),
                "rejectedCount": result.rejected_count, "candidateCount": result.candidate_count,
                "repairAttempted": result.repair_attempted, "modelCalls": result.model_calls,
                "duplicateCount": result.duplicate_count}
    body = build_content(course, lesson, revision, compiler, scenes, result.points, coverage)
    return PreparedContent(result.points, coverage, body)
