"""平台上下文按显式课时隔离；所有外部边界均使用内存桩。"""
import copy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.api.routes import student_bridge as bridge


@pytest.fixture
def context_setup(monkeypatch):
    monkeypatch.setattr(bridge, "check_student_service_key", lambda key: None)
    monkeypatch.setattr(bridge, "verify_launch_token", lambda token: {
        "uid": "00000000-0000-0000-0000-000000000001",
        "cid": "00000000-0000-0000-0000-000000000002"})
    monkeypatch.setattr(bridge, "_resolve_launch_context", lambda session, payload: None)
    lessons = [{"id": f"L{n}", "title": f"Lesson {n}", "order": n,
                "classroom": {"id": f"C{n}", "playerUrl": f"/player/{n}",
                              "scenes": [{"id": f"S{n}", "title": f"Topic {n}",
                                          "actions": [{"type": "speech", "text": f"BODY_{n}"}]}]}}
               for n in (1, 2)]
    entries = [{"id": f"K{n}", "title": f"Knowledge {n}", "resourceType": "knowledge-points",
                "scope": {"type": "lesson", "lessonId": f"L{n}"},
                "content": f"## Topic {n}\n- Expected {n}"} for n in (1, 2)]
    entries += [{"id": "shared", "scope": {"type": "course"}, "content": "Shared"},
                {"id": "unknown", "content": "Unbound"},
                {"id": "M1", "scope": {"type": "lesson", "lessonId": "L1"}, "content": "OTHER_MATERIAL"},
                {"id": "M2", "scope": {"type": "lesson", "lessonId": "L2"}, "content": "Selected"}]
    monkeypatch.setattr(bridge, "_published_lessons", lambda *args: copy.deepcopy(lessons))
    monkeypatch.setattr(bridge, "_published_package_payload", lambda *args: {
        "id": "pub", "version": 1, "entries": copy.deepcopy(entries)})
    monkeypatch.setattr(bridge, "_issue_playback_grant", lambda *args: "selected-grant")
    session = Mock()
    session.execute.return_value = SimpleNamespace(first=lambda: ("Course",))
    return session


def test_second_lesson_returns_only_selected_resources(context_setup):
    context = bridge.student_learning_context(
        bridge.LearningContextRequest(launch_token="token", lesson_id="L2"), context_setup)
    assert context["selectedLessonId"] == "L2"
    assert [x["id"] for x in context["lessons"]] == ["L2"]
    assert context["classroom"]["id"] == "C2"
    assert [x["id"] for x in context["knowledgePackage"]["entries"]] == ["K2", "shared", "M2"]
    assert context["knowledgePackage"]["rubric"]["knowledgePoints"][0]["title"] == "Topic 2"
    assert "BODY_1" not in str(context)
    assert "OTHER_MATERIAL" not in str(context)
    assert [x["id"] for x in context["lessonCatalog"]] == ["L1", "L2"]
    assert all("classroom" not in x for x in context["lessonCatalog"])


def test_no_selection_returns_catalog_only(context_setup):
    context = bridge.student_learning_context(bridge.LearningContextRequest(launch_token="token"), context_setup)
    assert context["selectedLessonId"] is None
    assert context["lessons"] == []
    assert context["classroom"] is None
    assert context["knowledgePackage"]["entries"] == []
    assert "rubric" not in context["knowledgePackage"]
    assert "BODY_1" not in str(context)
    assert "BODY_2" not in str(context)


def test_unknown_lesson_is_rejected(context_setup):
    with pytest.raises(HTTPException) as exc:
        bridge.student_learning_context(bridge.LearningContextRequest(launch_token="token", lesson_id="missing"),
                                        context_setup)
    assert exc.value.status_code == 404


def test_only_other_lesson_knowledge_is_never_used():
    entries = [{"resourceType": "knowledge-points", "scope": {"type": "lesson", "lessonId": "L1"},
                "content": "## Other topic\n- Other fact"}]
    assert bridge._knowledge_artifact_rubric(entries, "L2") is None
