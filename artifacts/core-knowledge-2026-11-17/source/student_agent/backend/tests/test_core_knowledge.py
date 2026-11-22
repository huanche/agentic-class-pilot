"""New extraction protocol crosses the same content and teaching Interface as callers."""
from copy import deepcopy
import json
import pytest
from backend.content import knowledge, lesson_content
from backend.content.knowledge_schema import submit_knowledge_points
from backend.teaching import service
from backend.infrastructure import model
from test_typed_knowledge import CORE, MATERIALS, run, submission


def test_core_content_roundtrip_teaching_and_feedback(monkeypatch):
    run(monkeypatch, submission(CORE))
    result = knowledge.learning_points(MATERIALS, "course", "lesson", course_name="程序设计基础")
    body = lesson_content.build("course", "lesson", "rev", "extractor-v3", result.points, MATERIALS)
    body = json.loads(json.dumps(body))
    lesson_content.validate(body)
    assert body["schemaVersion"] == 3
    assert body["topics"][0]["explanation"] == CORE["explanation"]
    session = {"id": "core-test", "phase": "video", "lessonId": "lesson", "videoRevision": "rev",
               "context": {"courseId": "course"}, "dialogue": service.new_dialogue(result.points),
               "messages": [], "lessonContent": body}
    session = lesson_content.bind(session)
    session.update(service.start_discussion(session))
    assert CORE["name"] in session["messages"][-1]["text"]
    calls = []
    def complete(system, user):
        calls.append(json.loads(user))
        if len(calls) % 2:
            return json.dumps({"intent": "answer", "assessments": [{"id": result.points[0]["id"],
                              "result": "mastered", "evidence": "准确说明初始化、判断和更新顺序"}]})
        return "你说明了执行顺序。初始化会在每轮都执行吗？"
    monkeypatch.setattr(model, "complete", complete)
    session.update(service.classroom_turn(session, "先初始化，再判断；满足条件执行循环体，更新后再判断。"))
    assert calls[0]["points"][0]["content"] == CORE["explanation"]
    assert session["dialogue"]["points"][0]["status"] == "mastered"
    session.update(service.finish(session))
    assert session["phase"] == "done" and session["feedback"]
    lesson_content.validate(session["lessonContent"])


@pytest.mark.parametrize("change", ["explanation", "title", "type"])
def test_rehashed_but_inconsistent_core_content_is_rejected(change):
    points = knowledge.compile_points(submit_knowledge_points(points=[CORE]), scope=("c", "l"))
    body = lesson_content.build("c", "l", "r", "v3", points, MATERIALS)
    body["points"][0][change] = "tampered"
    body["contentId"] = "content:" + lesson_content.digest({k:v for k,v in body.items() if k != "contentId"})
    with pytest.raises(ValueError):
        lesson_content.validate(body)


def test_publication_worker_and_persisted_session_use_core_protocol(pg, monkeypatch):
    from backend import internal_platform
    from backend.infrastructure import published_knowledge, persistence
    from backend.content.context import classroom_materials
    monkeypatch.setenv("STUDENT_SERVICE_KEY", "test-key")
    monkeypatch.setattr(internal_platform, "_db", pg)
    client = run(monkeypatch, submission(CORE))
    scenes = [{"id": "one", "title": "循环", "visibleText": ["先初始化，再判断，执行循环体，更新后再判断。"]}]
    body = internal_platform.PublishedLessonKnowledgeRequest(courseId="course", courseName="程序设计基础",
        lessonId="lesson", videoRevision="a"*64, classroomId="room", scenes=scenes)
    internal_platform.enqueue_published_lesson_knowledge(body, "test-key")
    assert published_knowledge.process_next()
    result = published_knowledge.read("course", "lesson", "a"*64)
    assert result["status"] == "ready" and result["contentModel"]["schemaVersion"] == 3
    assert json.loads(client.seen[0][1].content)["course_name"] == "程序设计基础"
    session = {"id": "core-persist", "phase": "video", "lessonId": "lesson", "videoRevision": "a"*64,
               "classroomId": "room", "context": {"courseId": "course", "userId": "student", "publication": {"id": "pub", "version": 1}},
               "dialogue": service.new_dialogue(result["points"]), "messages": []}
    session = lesson_content.bind(session, result)
    persistence.save(session, 0)
    restored = persistence.restore("core-persist")
    assert restored["lessonContent"]["schemaVersion"] == 3
    assert restored["dialogue"]["points"][0]["name"] == CORE["name"]
    assert "type" not in restored["dialogue"]["points"][0]
    restored.update(service.start_discussion(restored))
    assert CORE["name"] in restored["messages"][-1]["text"]


def test_actual_server_starts_with_isolated_database(pg, monkeypatch, tmp_path):
    import os
    from pathlib import Path
    import socket
    import subprocess
    import sys
    import time
    import urllib.request
    monkeypatch.setenv("PLATFORM_AUTH_URL", "http://127.0.0.1:1/api/v1")
    monkeypatch.setenv("PLATFORM_TO_STUDENT_KEY", "isolated-startup-test")
    monkeypatch.setenv("STUDENT_AGENT_API_KEY", "isolated-no-provider-request")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    checks = {}
    with (tmp_path / "startup.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1",
                                    "--port", str(port)], cwd=Path(__file__).resolve().parents[2], stdout=log, stderr=log)
        try:
            for _ in range(80):
                if process.poll() is not None:
                    break
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/session/health", timeout=1) as response:
                        checks["health"] = {"status": response.status, "body": json.loads(response.read())}
                    break
                except Exception:
                    time.sleep(.25)
            assert checks, (tmp_path / "startup.log").read_text(encoding="utf-8")
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/app/", timeout=5) as response:
                html = response.read().decode()
                checks["frontend"] = {"status": response.status, "htmlLength": len(html)}
                assert "<html" in html
            checks["isolatedDatabase"] = True
            checks["platformAuthenticationTested"] = False
        finally:
            process.terminate()
            process.wait(timeout=10)
    if os.environ.get("STUDENT_CORE_EVIDENCE_DIR"):
        out = Path(os.environ["STUDENT_CORE_EVIDENCE_DIR"])
        (out / "startup-smoke.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
        (out / "server-startup.log").write_text((tmp_path / "startup.log").read_text(encoding="utf-8"), encoding="utf-8")
