"""Exercise the production progress SQL without a PostgreSQL service."""
import ast
import json
from pathlib import Path
import uuid

from sqlalchemy import create_engine, text


def test_current_published_lessons_exclude_catalog_and_historical_sessions():
    source = Path(__file__).parents[2] / "app/api/routes/student_bridge.py"
    function = next(node for node in ast.parse(source.read_text(encoding="utf-8")).body
                    if isinstance(node, ast.FunctionDef) and node.name == "_course_learning_progress")
    namespace = {"uuid": uuid, "text": text}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
    progress = namespace["_course_learning_progress"]
    with create_engine("sqlite://").connect() as db:
        db.execute(text("ATTACH DATABASE ':memory:' AS teacher"))
        db.execute(text("ATTACH DATABASE ':memory:' AS student"))
        db.execute(text("CREATE TABLE teacher.mentra_course_artifacts (course_id TEXT, status TEXT, payload JSON)"))
        db.execute(text("CREATE TABLE teacher_course_link (course_id TEXT, external_course_id TEXT)"))
        db.execute(text("CREATE TABLE student.student_sessions (session_key TEXT, user_id TEXT, course_id TEXT, classroom_id TEXT, last_active_at TEXT, ended_at TEXT)"))
        db.execute(text("CREATE TABLE student.learning_events (session_key TEXT, user_id TEXT, course_id TEXT, event_type TEXT)"))
        db.execute(text("CREATE TABLE student.knowledge_mastery (user_id TEXT, course_id TEXT, stars INTEGER)"))
        db.execute(text("INSERT INTO teacher_course_link VALUES ('course', 'teacher-course')"))
        for classroom, visible in [('A', 'true'), ('A', 'true'), ('B', 'true'), ('hidden', 'false')]:
            db.execute(text("INSERT INTO teacher.mentra_course_artifacts VALUES ('teacher-course', 'published', :payload)"),
                       {"payload": json.dumps({"classroomId": classroom, "classVisible": visible, "classPublicationId": "pub"})})
        for sid, classroom, event in [('one', 'A', 'lesson_began'), ('again', 'A', 'media_done'),
                                      ('old', 'removed', 'lesson_began'), ('catalog', 'none', 'session_started'),
                                      ('preview', 'B', 'session_started'), ('hidden', 'hidden', 'lesson_began')]:
            db.execute(text("INSERT INTO student.student_sessions VALUES (:sid, 'user', 'course', :classroom, '2026-10-15', NULL)"), {"sid": sid, "classroom": classroom})
            db.execute(text("INSERT INTO student.learning_events VALUES (:sid, 'user', 'course', :event)"), {"sid": sid, "event": event})
        result = progress(db, 'user', 'course')
        assert result['totalLessons'] == 2
        assert result['learnedLessons'] == 1
        assert result['percent'] == 50
        assert progress(db, 'other-user', 'course')['learnedLessons'] == 0
        db.execute(text("INSERT INTO student.learning_events VALUES ('preview', 'user', 'course', 'lesson_began')"))
        assert progress(db, 'user', 'course')['learnedLessons'] == 2
        assert progress(db, 'user', 'empty-course')['totalLessons'] == 0


def test_catalog_deduplicates_classrooms_with_contiguous_order():
    source = Path(__file__).parents[2] / "app/api/routes/student_bridge.py"
    function = next(node for node in ast.parse(source.read_text(encoding="utf-8")).body
                    if isinstance(node, ast.FunctionDef) and node.name == "_published_lessons")
    class Session:
        def execute(self, query, params):
            return self
        def all(self):
            return [('first', '第一课', 'A', '1'), ('duplicate', '重复', 'A', '2'), ('second', '第二课', 'B', '3')]
    namespace = {"uuid": uuid, "text": text, "SessionDep": Session,
                 "_classroom_view": lambda session, classroom: {"title": classroom},
                 "_issue_playback_grant": lambda *args: "test-grant"}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
    lessons = namespace["_published_lessons"](Session(), 'course', 'user')
    assert [lesson['id'] for lesson in lessons] == ['lesson-first', 'lesson-second']
    assert [lesson['order'] for lesson in lessons] == [1, 2]
