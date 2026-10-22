"""旧会话空目录恢复：只补同课时同发布版的知识点，不重置学习进度。"""
import copy
import json
import unittest
from pathlib import Path
from unittest import mock

from apps.integration import course_adapter


class EmptyCatalogRecoveryTests(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).parent / "fixtures" / "platform-learning-context-v1.json"
        context = course_adapter.from_platform_payload(json.loads(fixture.read_text(encoding="utf-8")))
        self.state = {"learning_context": context.model_dump(), "lesson_id": context.lessons[0].id}
        self.state["lesson_plan"] = course_adapter.load_plan_for_session(self.state)
        self.state["lesson_plan"]["knowledge_points"] = []
        self.state["lesson_plan"]["evaluation"]["knowledge_points"] = []
        for segment in self.state["lesson_plan"]["segments"]:
            segment["knowledge_point_ids"] = []
        self.state.update({"host_phase": "tutoring", "tutoring_stats": {"correct": 2},
                           "tutoring_question": {"kp_id": "", "question": "通用复习题"},
                           "tutoring_stars": {"old-kp": 2}, "dialogue_log": [{"role": "student", "text": "保留记录"}]})

    def test_empty_catalog_is_repaired_without_resetting_progress(self):
        saved = copy.deepcopy(self.state)
        self.assertTrue(course_adapter.repair_empty_knowledge_catalog(self.state))
        self.assertEqual(self.state["lesson_plan"]["knowledge_points"][0]["title"], "心理沙盘游戏初识")
        self.assertIsNone(self.state["tutoring_question"])
        for key in ("host_phase", "dialogue_log", "tutoring_stars", "tutoring_stats"):
            self.assertEqual(self.state[key], saved[key])
        self.assertFalse(course_adapter.repair_empty_knowledge_catalog(self.state))

    def test_different_publication_or_lesson_is_not_rebound(self):
        for field, value in (("publication_id", "another-version"), ("publication_version", 999),
                             ("lesson_id", "another-lesson"), ("course_id", "another-course")):
            with self.subTest(field=field):
                state = copy.deepcopy(self.state)
                state["lesson_plan"][field] = value
                before = copy.deepcopy(state)
                self.assertFalse(course_adapter.repair_empty_knowledge_catalog(state))
                self.assertEqual(state, before)

    def test_existing_catalog_and_pending_question_are_not_replaced(self):
        self.state["lesson_plan"]["knowledge_points"] = [{"id": "existing", "title": "已有知识点"}]
        before = copy.deepcopy(self.state)
        self.assertFalse(course_adapter.repair_empty_knowledge_catalog(self.state))
        self.assertEqual(self.state, before)

    def test_start_reentry_repairs_the_catalog_exposed_to_the_student(self):
        """真实 start→state 路由重入旧辅导，目录和开场均恢复且不重置进度。"""
        import threading

        from fastapi.testclient import TestClient

        from apps import server
        from apps.integration import config, launch_context, platform_client
        import agent

        sid = "test-empty-catalog-reentry"
        context = self.state["learning_context"]
        state = agent.initial_state(sid, context["user_id"], context["course_id"])
        state.update(self.state)
        state.update({"lesson_id": context["selected_lesson_id"], "lesson_status": "running",
                      "tutoring_planned_end_at": "2026-10-21T12:00:00+00:00", "tutoring_planned_minutes": 15})
        server.SESSIONS[sid] = {
            "state": state, "messages": [], "lock": threading.Lock(),
            "stop": threading.Event(), "thread": mock.Mock(), "time_scale": 1.0,
        }
        self.addCleanup(server.SESSIONS.pop, sid, None)
        payload = {"uid": context["user_id"], "cid": context["course_id"], "rid": "classroom",
                   "pub": {"publicationId": context["publication"]["id"],
                           "version": context["publication"]["version"]}}
        fixture = json.loads((Path(__file__).parent / "fixtures" /
                              "platform-learning-context-v1.json").read_text(encoding="utf-8"))
        with mock.patch.object(config, "require_platform_config"), \
                mock.patch.object(launch_context, "verify_launch_token", return_value=payload), \
                mock.patch.object(platform_client, "fetch_learning_context", return_value=fixture), \
                mock.patch.object(server, "_persist"), \
                mock.patch.object(server, "_persist_session_record"), \
                mock.patch.object(server, "_record_learning_event"):
            client = TestClient(server.app)
            response = client.post("/api/session/start", json={"session_id": sid, "launch_token": "test-token",
                                                              "lesson_id": context["selected_lesson_id"]})
            self.assertEqual(response.status_code, 200, response.text)
            public = client.get(f"/api/session/{sid}/state").json()
        self.assertEqual(public["phase"], "tutoring")
        self.assertEqual(public["tutoring"]["knowledge_points"][0]["title"], "心理沙盘游戏初识")
        self.assertEqual(public["tutoring"]["planned_end_at"], "2026-10-21T12:00:00+00:00")
        self.assertEqual(state["tutoring_stats"], {"correct": 2})
        opening, _ = agent.tutoring_opening(state)
        self.assertIn("1. 心理沙盘游戏初识", opening)
        self.assertNotIn("没有登记知识点", opening)


if __name__ == "__main__":
    unittest.main()
