"""Fixed pre-refactor outputs: no provider requests or database access."""
import json
from pathlib import Path

from backend.content.context import classroom_materials
from backend.content import knowledge, lesson_content, preparation
from backend.infrastructure import published_knowledge
from backend.content.knowledge_schema import StoredKnowledgePoints


def test_historical_content_preserves_fixed_points_and_content_identity():
    fixture = json.loads((Path(__file__).parent / "fixtures/preparation_contract.json").read_text(encoding="utf-8"))
    expected = fixture["expected"]
    points = knowledge.compile_points(StoredKnowledgePoints(points=fixture["submission"]),
                                      scope=("contract-course", "contract-lesson"))
    body = preparation.build_content(
        "contract-course", "contract-lesson", "contract-revision",
        expected["extractorHash"], fixture["scenes"], points, expected["coverage"])
    lesson_content.validate(body)
    assert classroom_materials(fixture["scenes"]) == expected["materials"]
    assert points == expected["points"]
    assert lesson_content.reference(body) == expected["contentRef"]
    assert body["coverageGaps"] == expected["coverageGaps"]
    assert published_knowledge.EXTRACTOR_HASH != expected["extractorHash"]


def test_material_truncation_preserves_exact_prefix_and_empty_scene_filtering():
    materials = classroom_materials([
        {"id": "empty", "order": 1},
        {"id": "long", "order": 2, "visibleText": ["x" * 6001],
         "actions": [{"type": "speech", "text": "beyond the existing truncation"}]},
    ])
    assert materials == [{"id": "scene:long", "title": "第 2 段内容",
                          "content": "画面文字：" + "x" * 5995,
                          "source": "published-classroom-scene"}]
