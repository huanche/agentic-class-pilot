"""Publication projection tests runnable without a database or backend dependencies.

Load the production projection function from its AST so these tests exercise
its filtering and result shape while substituting only the SQL session.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
import uuid

SOURCE = Path(__file__).parents[2] / "app/api/routes/student_bridge.py"
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "published_course_entries")
namespace = {"SessionDep": object, "uuid": uuid, "text": lambda value: value,
             "settings": SimpleNamespace(TEACHER_PUBLIC_URL="https://teacher.example")}
exec(compile(ast.Module(body=[function], type_ignores=[]), str(SOURCE), "exec"), namespace)
project = namespace["published_course_entries"]

class Session:
    def __init__(self, course, artifacts=()):
        self.course, self.artifacts = course, artifacts
        self.calls = []
    def execute(self, sql, params):
        self.calls.append((sql, params))
        return SimpleNamespace(first=lambda: (self.course,) if self.course else None,
                               all=lambda: [(a,) for a in self.artifacts])

class PublicationBoundaryTests(unittest.TestCase):
    def test_only_explicitly_published_files_are_projected(self):
        published = {"classVisible": True, "classPublicationId": "CLS-1"}
        course = {"id": "legacy-course", "modules": [{"lessons": [{"id": "lesson-1", "files": [
            {"id": "draft", "content": "secret"},
            {"id": "legacy", "classVisible": True},
            {"id": "knowledge", "title": "Knowledge", "content": "released", **published},
        ]}]}], "materials": [
            {"id": "private-material", "name": "secret"},
            {"id": "material", "name": "Uploaded PDF", **published},
        ]}
        session = Session(course, [{"id": "private-artifact"},
                                   {"id": "artifact", "title": "Slides", **published}])
        entries = project(session, uuid.UUID(int=1))
        self.assertEqual([e["id"] for e in entries], ["artifact", "knowledge", "material"])
        self.assertEqual(entries[1]["scope"]["lessonId"], "lesson-1")
        self.assertTrue(entries[2]["url"].endswith("/legacy-course/materials/material"))
        self.assertTrue(all(call[1]["id"] == uuid.UUID(int=1) for call in session.calls))
        self.assertIn("c.status='active'", session.calls[0][0])
        self.assertIn("a.status='published'", session.calls[1][0])

    def test_missing_or_inactive_course_has_no_files(self):
        self.assertEqual(project(Session(None), uuid.UUID(int=1)), [])

    def test_hidden_file_with_publication_id_stays_private(self):
        course = {"id": "c", "modules": [], "materials": [
            {"id": "hidden", "classVisible": False, "classPublicationId": "CLS-2"}]}
        self.assertEqual(project(Session(course), uuid.UUID(int=1)), [])

if __name__ == "__main__":
    unittest.main()
