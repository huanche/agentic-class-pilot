"""所选课时必须贯穿请求、内部上下文与教学计划，禁止首课时回退。"""
import copy
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from apps.integration import course_adapter


def lesson_payload():
    def lesson(number):
        return {
            "id": f"L{number}", "title": f"Lesson {number}", "order": number,
            "classroom": {"id": f"C{number}", "playerUrl": f"https://example.test/{number}",
                          "scenes": [{"id": f"S{number}", "title": f"Topic {number}",
                                      "actions": [{"id": f"A{number}", "type": "speech",
                                                   "text": f"Lesson {number} narration"}]}]},
        }
    return {
        "schemaVersion": 1, "userId": "u1", "courseId": "course1", "courseTitle": "Course",
        "publication": {"id": "pub1", "version": 1}, "selectedLessonId": "L2",
        "lessonCatalog": [{"id": f"L{n}", "title": f"Lesson {n}", "order": n} for n in (1, 2)],
        "lessons": [lesson(1), lesson(2)], "classroom": lesson(1)["classroom"],
        "knowledgePackage": {
            "title": "Course", "summary": "Summary",
            "entries": [
                {"id": "M1", "title": "Other material", "content": "OTHER_LESSON_SECRET",
                 "scope": {"type": "lesson", "lessonId": "L1"}},
                {"id": "M2", "title": "Selected material", "content": "Selected content",
                 "scope": {"type": "lesson", "lessonId": "L2"}},
                {"id": "shared", "title": "Shared", "content": "Shared content",
                 "scope": {"type": "course"}},
                {"id": "unknown", "title": "Unbound", "content": "Unbound content"},
            ],
            "rubric": {"knowledgePoints": [
                {"id": "K2", "title": "Topic 2", "expectedConcepts": ["Selected fact"]}]},
        },
    }


class LessonContextScopeTests(unittest.TestCase):
    def test_start_preserves_selected_lesson_and_scopes_state(self):
        from apps import server
        from apps.integration import config, launch_context, platform_client

        sid = "test-selected-lesson-scope"
        self.addCleanup(server.SESSIONS.pop, sid, None)
        token = {"uid": "u1", "cid": "course1", "rid": "C1",
                 "pub": {"publicationId": "pub1", "version": 1}}
        def create_session(sid, student_id, lesson_id, time_scale):
            state = server.SESSIONS[sid]["state"]
            state.update(student_id=student_id, lesson_id=lesson_id, lesson_status="idle")
            return state

        with mock.patch.object(config, "require_platform_config"), \
                mock.patch.object(launch_context, "verify_launch_token", return_value=token), \
                mock.patch.object(platform_client, "fetch_learning_context", return_value=lesson_payload()) as fetch, \
                mock.patch.object(server, "_restore", return_value=None), \
                mock.patch.object(server, "_persist") as persist, \
                mock.patch.object(server, "_persist_session_record"), \
                mock.patch.object(server, "_record_learning_event"), \
                mock.patch.object(server, "_create_session", side_effect=create_session):
            client = TestClient(server.app)
            response = client.post("/api/session/start", json={
                "session_id": sid, "launch_token": "test-token", "lesson_id": "L2"})
            self.assertEqual(response.status_code, 200, response.text)
            state = server.SESSIONS[sid]["state"]
            self.assertEqual(state["lesson_id"], "L2")
            context = state["learning_context"]
            self.assertEqual([x["id"] for x in context["lessons"]], ["L2"])
            self.assertEqual(context["classroom"]["id"], "C2")
            self.assertEqual([x["id"] for x in context["knowledge_package"]["entries"]], ["M2", "shared"])
            self.assertEqual(context["evaluation"]["knowledge_points"][0]["id"], "K2")
            self.assertNotIn("OTHER_LESSON_SECRET", str(persist.call_args))
            fetch.assert_called_once_with("test-token", lesson_id="L2")
            plan = course_adapter.load_plan_for_session(state)
            self.assertEqual(plan["lesson_id"], "L2")
            self.assertIn("Lesson 2 narration", plan["segments"][0]["content"])
            self.assertEqual(plan["knowledge_points"][0]["id"], "K2")
            detail = client.get(f"/api/session/lesson?sessionId={sid}&lessonId=L2")
            self.assertEqual(detail.json()["classroomId"], "C2")

    def test_plan_never_defaults_to_first_lesson(self):
        context = course_adapter.from_platform_payload(lesson_payload())
        for lesson_id in (None, "missing", "L1"):
            with self.subTest(lesson_id=lesson_id):
                with self.assertRaises(course_adapter.ContextContractError):
                    course_adapter.load_plan_for_session({"learning_context": context.model_dump(),
                                                          "lesson_id": lesson_id})

    def test_adapter_rejects_wrong_rubric_binding(self):
        payload = lesson_payload()
        payload["selectedLessonId"] = "L1"
        with self.assertRaises(course_adapter.ContextContractError):
            course_adapter.from_platform_payload(payload, lesson_id="L2")

    def test_catalog_context_has_no_teaching_resources(self):
        payload = lesson_payload()
        payload["selectedLessonId"] = None
        context = course_adapter.from_platform_payload(payload)
        self.assertEqual(context.lessons, [])
        self.assertIsNone(context.classroom)
        self.assertEqual(context.knowledge_package.entries, [])
        self.assertEqual(context.evaluation.knowledge_points, [])
        self.assertEqual([x.id for x in context.lesson_catalog], ["L1", "L2"])

    def test_adapter_does_not_mutate_input(self):
        payload = lesson_payload()
        before = copy.deepcopy(payload)
        course_adapter.from_platform_payload(payload)
        self.assertEqual(payload, before)

    def test_scoped_context_survives_disk_restore(self):
        from apps import server
        context = course_adapter.from_platform_payload(lesson_payload(), lesson_id="L2")
        state = server.initial_state("scoped-restore", "u1", "L2")
        state["learning_context"] = context.model_dump()
        state["lesson_plan"] = course_adapter.load_plan_for_session(state)
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(server, "SESSIONS_DIR", Path(directory)):
            server._persist("scoped-restore", state)
            restored = server._restore("scoped-restore")
            self.assertEqual(restored["learning_context"]["selected_lesson_id"], "L2")
            self.assertNotIn("OTHER_LESSON_SECRET", str(restored))
            self.assertEqual(restored["lesson_plan"]["lesson_id"], "L2")

    def test_detail_cannot_read_another_lesson_in_same_session(self):
        from apps import server
        sid = "test-scoped-detail"
        context = course_adapter.from_platform_payload(lesson_payload(), lesson_id="L2")
        server.SESSIONS[sid] = {"state": {"learning_context": context.model_dump()}}
        self.addCleanup(server.SESSIONS.pop, sid, None)
        with mock.patch.object(server, "_preload_disk_sessions"):
            client = TestClient(server.app)
            self.assertEqual(client.get(f"/api/session/lesson?sessionId={sid}&lessonId=L1").status_code, 404)
            self.assertEqual(client.get(f"/api/session/lesson?sessionId={sid}").status_code, 400)

    def test_catalog_session_cannot_begin(self):
        from apps import server
        sid = "test-catalog-begin"
        payload = lesson_payload()
        payload["selectedLessonId"] = None
        context = course_adapter.from_platform_payload(payload)
        server.SESSIONS[sid] = {"state": {"learning_context": context.model_dump()}}
        self.addCleanup(server.SESSIONS.pop, sid, None)
        self.assertEqual(TestClient(server.app).post(f"/api/session/{sid}/begin").status_code, 409)

    def test_start_rejects_cross_lesson_and_old_version_without_overwriting(self):
        from apps import server
        from apps.integration import config, launch_context, platform_client

        context = course_adapter.from_platform_payload(lesson_payload(), lesson_id="L2")
        token = {"uid": "u1", "cid": "course1", "rid": "C1",
                 "pub": {"publicationId": "pub1", "version": 1}}
        for mismatch in ("lesson", "version", "legacy"):
            with self.subTest(mismatch=mismatch):
                sid = "test-scope-conflict-" + mismatch
                state = server.initial_state(sid, "u1", "L2")
                state["learning_context"] = context.model_dump()
                state["lesson_plan"] = course_adapter.load_plan_for_session(state)
                state["lesson_status"] = "running"
                if mismatch == "lesson":
                    state["lesson_id"] = "L1"
                elif mismatch == "version":
                    state["lesson_plan"]["publication_version"] = 999
                else:
                    state["learning_context"].pop("selected_lesson_id")
                before = copy.deepcopy(state)
                server.SESSIONS[sid] = {"state": state, "lock": threading.Lock()}
                self.addCleanup(server.SESSIONS.pop, sid, None)
                with mock.patch.object(config, "require_platform_config"), \
                        mock.patch.object(launch_context, "verify_launch_token", return_value=token), \
                        mock.patch.object(platform_client, "fetch_learning_context", return_value=lesson_payload()), \
                        mock.patch.object(server, "_persist") as persist:
                    response = TestClient(server.app).post("/api/session/start", json={
                        "session_id": sid, "lesson_id": "L2", "launch_token": "test-token"})
                    self.assertEqual(response.status_code, 409, response.text)
                    self.assertEqual(server.SESSIONS[sid]["state"], before)
                    persist.assert_not_called()
