"""Published knowledge is shared and never regenerated for each student."""
from threading import Lock
from pathlib import Path
import sys

from fastapi import BackgroundTasks

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend import main


def _session():
    return {"id": "lesson-test", "context": {"courseId": "course-1"},
            "lessonId": "lesson-1", "videoRevision": "revision-1",
            "phase": "video", "messages": [], "dialogue": None,
            "preparation": "pending", "lock": Lock()}


def test_student_reads_published_points_without_scheduling_model(monkeypatch):
    monkeypatch.setattr(main.persistence, "save", lambda *args: None)
    monkeypatch.setattr(main.published_knowledge, "read", lambda *args: {
        "status": "ready", "points": [{"id": "p1", "title": "电路交换"}],
        "coverage": {"acceptedCount": 1}, "error": None,
    })
    monkeypatch.setattr(main, "prepared_dialogue", lambda *args: (_ for _ in ()).throw(
        AssertionError("student must not call the model")))
    session = _session()
    tasks = BackgroundTasks()
    main.schedule_preparation(session, tasks)
    assert tasks.tasks == []
    main.sync_published_preparation(session)
    assert session["preparation"] == "ready"
    assert session["dialogue"]["points"][0]["title"] == "电路交换"


def test_failed_published_job_can_be_retried_without_student_generation(monkeypatch):
    session = _session()
    monkeypatch.setattr(main.published_knowledge, "read", lambda *args: {
        "status": "failed", "points": None, "coverage": None, "error": "timeout",
    })
    main.sync_published_preparation(session)
    assert session["preparation"] == "error"
    assert "重试" in session["preparationError"]
