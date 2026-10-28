"""Published classroom snapshots create one durable knowledge job."""
import ast
import hashlib
import json
from pathlib import Path
import uuid
from types import SimpleNamespace

SOURCE = Path(__file__).parents[2] / "app/api/routes/student_bridge.py"
function = next(node for node in ast.parse(SOURCE.read_text(encoding="utf-8")).body
                if isinstance(node, ast.FunctionDef)
                and node.name == "ensure_published_knowledge_job")
namespace = {"SessionDep": object, "uuid": uuid, "hashlib": hashlib, "json": json,
             "text": lambda sql: sql,
             "settings": SimpleNamespace(STUDENT_KNOWLEDGE_ENQUEUE_MODE="legacy")}
exec(compile(ast.Module(body=[function], type_ignores=[]), str(SOURCE), "exec"), namespace)


def test_job_uses_same_video_revision_as_student():
    recorded = []

    class Session:
        def execute(self, sql, params):
            recorded.append((sql, params))

        def commit(self):
            recorded.append(("commit", None))

    classroom = {"id": "room-1", "scenes": [{"id": "s1", "visibleText": ["电路交换"]}]}
    revision = namespace["ensure_published_knowledge_job"](
        Session(), uuid.UUID(int=1), "lesson-1", classroom, 123)
    expected = hashlib.sha256(json.dumps(
        ["room-1", 123, classroom["scenes"]], sort_keys=True, ensure_ascii=False,
    ).encode()).hexdigest()
    assert revision == expected
    assert recorded[0][1]["revision"] == expected
    assert recorded[0][1]["lesson"] == "lesson-1"
    assert "ON CONFLICT" in recorded[0][0]
    assert recorded[1][0] == "commit"
