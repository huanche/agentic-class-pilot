"""Old-session replay reads classroom scenes only through the platform."""

import sys
from pathlib import Path

from backend.contracts import SessionError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.infrastructure import persistence, platform_client


def test_api_mode_fetches_scenes_from_platform(monkeypatch):
    calls = {}
    monkeypatch.setattr(platform_client, "fetch_classroom_scenes",
                        lambda classroom_id: calls.update(id=classroom_id) or [{"id": "s1"}])
    assert persistence.classroom_scenes("room-1") == [{"id": "s1"}]
    assert calls == {"id": "room-1"}


def test_api_mode_keeps_empty_scenes_when_platform_unavailable(monkeypatch):
    """平台不可用时回退为空场景，不阻断旧会话回放。"""
    monkeypatch.delenv("STUDENT_DATABASE_URL", raising=False)

    def unavailable(classroom_id):
        raise SessionError(503, "平台服务暂不可用")

    monkeypatch.setattr(platform_client, "fetch_classroom_scenes", unavailable)
    assert persistence.classroom_scenes("room-1") == []


def test_api_mode_never_touches_teacher_tables(monkeypatch):

    class Explode:
        def _db(self):
            raise AssertionError("direct database access in api mode")

    monkeypatch.setattr(persistence.database, "_db", Explode()._db)
    monkeypatch.setattr(platform_client, "fetch_classroom_scenes",
                        lambda classroom_id: [])
    assert persistence.classroom_scenes("room-1") == []
