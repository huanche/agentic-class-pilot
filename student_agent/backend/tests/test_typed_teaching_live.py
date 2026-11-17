"""Opt-in real-provider regression at the authenticated learning command seam.

This catches the archived repeated question, not general teaching quality. It
uses a synthetic learner and disposable PostgreSQL, never a production session.
"""
import json
import os
from difflib import SequenceMatcher
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from backend import main
from backend.infrastructure import persistence
from backend.teaching import service


@pytest.mark.skipif(os.environ.get("STUDENT_TEACHING_LIVE_REGRESSION") != "1",
                    reason="Opt in to real provider calls with STUDENT_TEACHING_LIVE_REGRESSION=1")
def test_stalled_learner_gets_a_different_explanation_instead_of_the_same_choice(pg, monkeypatch):
    report = json.loads((Path(__file__).resolve().parents[3] /
        "student_agent/docs/knowledge-teaching/validation/2026-11-06-live-model/run.json").read_text(encoding="utf-8"))
    prior_turns = report["turns"][36:38]
    last = prior_turns[-1]
    point = next(p for p in report["finalPoints"] if p["id"] == last["pointId"])
    state = service.new_dialogue([point])
    state.pop("mastery_version", None)  # Replay the archived protocol, not a new lesson.
    focus = state["points"][0]
    focus.update(status="partial", recall_done=True, recall_attempts=5, reinforce_attempts=2,
        attempts=7, task_question=last["questionBefore"], known_parts=last["knownParts"],
        gaps=last["gaps"], next_step=last["nextStep"],
        assessment_history=[{"stage": "reinforce", "round": i + 1, "result": "partial",
            "evidence": "只重复已经会的定义，没有回答当前情境", "studentText": turn["student"]}
            for i, turn in enumerate(prior_turns)],
        help_history=[{"stage": "reinforce", "kind": "hint", "text": turn["reply"]} for turn in prior_turns])
    state["stage"] = "reinforce"
    # Imported learner answers are already in assessment_history; don't invent
    # new command observations for those historical answers when seeding.
    messages = [{"role": "assistant", "text": turn["reply"], "phase": "reinforce"} for turn in prior_turns]
    sid = "live-regression-" + uuid4().hex
    persistence.save({"id": sid, "phase": "discussion", "lessonId": "lesson", "classroomId": "room",
        "context": {"userId": "student", "courseId": "course", "publication": {"id": "pub", "version": 1}},
        "videoRevision": "revision", "messages": messages, "courses": [], "preparation": "ready",
        "dialogue": state}, 0)
    monkeypatch.setenv("PLATFORM_TO_STUDENT_KEY", "live-regression-forward")
    client = TestClient(main.app, headers={"X-Platform-Learning-Key": "live-regression-forward",
        "X-Platform-Protocol": "platform-cookie-v1", "X-Platform-User-Id": "student", "X-Platform-Course-Id": "course"})
    before = client.get(f"/api/session/{sid}").json()
    view, replies = before, []
    for _ in range(3):
        response = client.post(f"/api/session/{sid}/commands", json={"commandId": uuid4().hex,
            "type": "submit_answer", "payload": {"text": report["turns"][38]["student"]},
            "expectedStateVersion": view["stateVersion"], "contentGeneration": view["contentGeneration"]})
        assert response.status_code == 200, response.text
        view = response.json()["sessionView"]
        replies.append(view["messages"][-1]["text"])
    output = Path(__file__).resolve().parents[3] / ".runtime/typed-teaching-live/command-regression.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"replies": replies, "beforeTask": before["currentTaskPublic"],
        "afterTask": view["currentTaskPublic"]}, ensure_ascii=False, indent=2), encoding="utf-8")
    assert view["currentTaskPublic"]["question"] == before["currentTaskPublic"]["question"]
    for reply in replies:
        assert not ("成功，还是出错" in reply and "直接加 1" in reply), reply
    for first, second in zip(replies, replies[1:]):
        # Narrow smoke alarm for near-verbatim repetition of this captured scene;
        # it is not a semantic teaching metric or a production rule.
        assert SequenceMatcher(None, first, second).ratio() < 0.85, (first, second)
        assert not ("下标：" in first and "下标：" in second), (first, second)
