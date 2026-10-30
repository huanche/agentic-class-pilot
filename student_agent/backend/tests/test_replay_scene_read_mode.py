"""Old-session replay reads classroom scenes via the platform in api mode."""

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agent import database, persistence, platform_client


def test_api_mode_fetches_scenes_from_platform(monkeypatch):
    monkeypatch.setenv("STUDENT_REPLAY_SCENE_READ_MODE", "api")
    calls = {}
    monkeypatch.setattr(platform_client, "fetch_classroom_scenes",
                        lambda classroom_id: calls.update(id=classroom_id) or [{"id": "s1"}])
    assert persistence.classroom_scenes("room-1") == [{"id": "s1"}]
    assert calls == {"id": "room-1"}


def test_api_mode_keeps_empty_scenes_when_platform_unavailable(monkeypatch):
    """平台不可用时回退为空场景，不阻断旧会话回放。"""
    monkeypatch.setenv("STUDENT_REPLAY_SCENE_READ_MODE", "api")
    monkeypatch.delenv("STUDENT_DATABASE_URL", raising=False)

    def unavailable(classroom_id):
        raise HTTPException(503, "平台服务暂不可用")

    monkeypatch.setattr(platform_client, "fetch_classroom_scenes", unavailable)
    assert persistence.classroom_scenes("room-1") == []


def test_api_mode_never_touches_teacher_tables(monkeypatch):
    monkeypatch.setenv("STUDENT_REPLAY_SCENE_READ_MODE", "api")

    class Explode:
        def _db(self):
            raise AssertionError("direct database access in api mode")

    monkeypatch.setattr(persistence.database, "_db", Explode()._db)
    monkeypatch.setattr(platform_client, "fetch_classroom_scenes",
                        lambda classroom_id: [])
    assert persistence.classroom_scenes("room-1") == []


def test_legacy_mode_keeps_direct_query(monkeypatch):
    monkeypatch.delenv("STUDENT_REPLAY_SCENE_READ_MODE", raising=False)

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query, params):
            assert "teacher.mentra_classrooms" in query
            assert params == ("room-1",)

            class Row:
                def fetchone(self):
                    return ([{"id": "s1"}],)

            return Row()

        commit = lambda self: None  # noqa: E731

    monkeypatch.setattr(persistence.database, "_db", Connection)
    monkeypatch.setenv("STUDENT_DATABASE_URL", "postgresql://test:test@localhost:1/app_test")
    assert persistence.classroom_scenes("room-1") == [{"id": "s1"}]
