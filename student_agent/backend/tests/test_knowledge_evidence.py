"""Evidence tolerates typography, but never accepts changed teaching content."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agent import knowledge


SOURCE = "牛顿第一定律：物体保持静止或匀速直线运动，除非受到外力作用。"
MATERIALS = [{"id": "scene:1", "source": "published-classroom-scene", "content": SOURCE}]


def point(quote=SOURCE, title="牛顿第一定律", source_id="scene:1"):
    return {"title": title, "evidence": [{"sourceId": source_id, "quote": quote}]}


def test_typography_maps_back_to_exact_source():
    result = knowledge.validate_candidates({"points": [point(
        quote="牛顿第一定律:物体保持静止或匀速直线运动,\n除非受到外力作用。"
    )]}, MATERIALS)
    assert not result.issues
    assert result.points[0]["content"] == SOURCE


def test_normalized_match_keeps_source_newlines():
    source = SOURCE.replace("运动", "运\n动")
    result = knowledge.validate_candidates({"points": [point()]}, [
        dict(MATERIALS[0], content=source)])
    assert result.points[0]["content"] == source


@pytest.mark.parametrize("candidate, reason", [
    (point(quote=SOURCE.replace("静止", "加速")), "quote_not_found:0"),
    (point(title="惯性"), "title_not_in_evidence"),
    (point(quote="牛顿第一定律"), "evidence_too_short"),
    (point(source_id="missing"), "unknown_source:0"),
    (point(source_id=[]), "unknown_source:0"),
])
def test_failures_have_specific_reasons(candidate, reason):
    result = knowledge.validate_candidates({"points": [candidate]}, MATERIALS)
    assert not result.points
    assert result.issues[0].reason == reason


def test_normalization_does_not_join_latin_words_or_change_numbers():
    assert knowledge._source_span("a b", "ab") is None
    assert knowledge._source_span("速率为10", "速率为100") is None


def test_one_failure_keeps_valid_points_without_retry(monkeypatch):
    calls = []
    def complete(*args):
        calls.append(1)
        return json.dumps({"points": [point(), point(title="惯性")]}, ensure_ascii=False)
    monkeypatch.setattr(knowledge, "_completion", complete)
    result = knowledge.learning_points(MATERIALS)
    assert len(calls) == 1
    assert [item["title"] for item in result.points] == ["牛顿第一定律"]
    assert result.partial is True
    assert result.rejected_count == 1
    assert result.candidate_count == 2
    assert result.repair_attempted is False


def test_all_invalid_points_still_fail(monkeypatch):
    monkeypatch.setattr(knowledge, "_completion", lambda *args:
                        json.dumps({"points": [point(title="惯性")]}, ensure_ascii=False))
    with pytest.raises(knowledge.KnowledgePreparationError) as captured:
        knowledge.learning_points(MATERIALS)
    assert captured.value.accepted_count == 0
    assert captured.value.rejected_count == 1
    assert captured.value.issues[0].reason == "title_not_in_evidence"
    assert "第 1 个知识点" in str(captured.value)
