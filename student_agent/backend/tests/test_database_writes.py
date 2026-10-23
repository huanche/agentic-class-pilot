"""Every classroom write must bind exactly the values sent to PostgreSQL."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agent import database


class StrictConnection:
    def __init__(self):
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params):
        assert query.count("%s") == len(params), "SQL placeholder count differs from bound parameters"
        self.statements.append((query, params))

    def commit(self):
        pass


@pytest.mark.parametrize("write", [
    lambda: database.record_event("session", "user", "course", "publication", "agent_state",
                                  {"phase": "video"}, event_id="begin"),
    lambda: database.upsert_message("session", "user", "course", "publication", 1,
                                    "student", "recall", "我的回答"),
    lambda: database.upsert_mastery("session", "user", "course", "publication", "point",
                                    4, "掌握", "独立解释", "video"),
])
def test_classroom_writes_bind_the_values_they_store(monkeypatch, write):
    connection = StrictConnection()
    monkeypatch.setattr(database, "_db", lambda: connection)
    write()
    assert len(connection.statements) == 1
