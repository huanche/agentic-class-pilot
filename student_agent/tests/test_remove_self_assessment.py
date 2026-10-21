"""自评下线回归：接口、旧状态清理、报告、顺序和时长不受影响。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from apps import server
from apps.integration import persistence
from apps.integration.data_cleanup import without_self_assessment
from apps import test_post_video_tutoring as tutoring_tests
from scripts.remove_self_assessment import clean_runtime
import agent


class SelfAssessmentRemovalTest(unittest.TestCase):
    sid = "test-remove-self-assessment"
    student_id = "test-remove-self-assessment-student"
    setUp = tutoring_tests.TutoringFlowTest.setUp
    _cleanup = tutoring_tests.TutoringFlowTest._cleanup
    _begin_demo_lesson = tutoring_tests.TutoringFlowTest._begin_demo_lesson

    def test_old_fields_absent_from_state_and_report(self):
        self._begin_demo_lesson()
        self.client.post(f"/api/session/{self.sid}/media/done", json={})
        state = server.SESSIONS[self.sid]["state"]
        state["tutoring_self_ratings"] = {"KP-001": 5}
        public = self.client.get(f"/api/session/{self.sid}/state").json()["tutoring"]
        self.assertNotIn("self_ratings", public)
        report, _ = agent.tutoring_feedback_payload(state)
        self.assertTrue(all("self_rating" not in kp for kp in report["knowledge_points"]))

        server._persist(self.sid, state)
        self.assertNotIn("tutoring_self_ratings", json.loads(server._path(self.sid).read_text(encoding="utf-8")))
        self.assertNotIn("tutoring_self_ratings", server._restore(self.sid))

    def test_old_cached_and_persisted_feedback_is_filtered(self):
        self._begin_demo_lesson()
        payload = {"knowledge_points": [{"kp_id": "KP-001", "system_stars": 3, "self_rating": 5}]}
        expected = {"knowledge_points": [{"kp_id": "KP-001", "system_stars": 3}]}
        server.SESSIONS[self.sid]["tutoring_reports"] = [
            {"version": 1, "payload": payload, "teacher_summary": "保留摘要"}]
        cached = self.client.get(f"/api/session/{self.sid}/tutoring-report").json()
        self.assertTrue(all("self_rating" not in kp for kp in cached["payload"]["knowledge_points"]))
        self.assertEqual(cached["payload"]["mastery_schema"], "knowledge-mastery/2")
        persistence.append_report_version(self.sid, "demo", "c", "p", payload)
        self.assertEqual(persistence.read_latest_report(self.sid)["payload"], expected)

    def test_model_cannot_reintroduce_retired_intent(self):
        with mock.patch.object(agent, "llm_available", return_value=True), \
                mock.patch.object(agent, "llm_chat", return_value='{"intent":"self_eval","kp_no":1,"rating":5}'):
            self.assertIsNone(agent._tutoring_classify_message("我掌握得很好", [("kp", "知识点")], False))

    def test_opening_and_model_prompt_only_ask_order_and_duration(self):
        self._begin_demo_lesson()
        response = self.client.post(f"/api/session/{self.sid}/media/done", json={}).json()
        self.assertNotIn("自评", response["reply_text"])
        self.assertIn("顺序", response["reply_text"])
        self.assertIn("分钟", response["reply_text"])
        with mock.patch.object(agent, "llm_available", return_value=True), \
                mock.patch.object(agent, "llm_chat", return_value='{"intent":"time_change","minutes":10}') as chat:
            result = agent._tutoring_classify_message("十分钟左右", [("kp", "知识点")], False)
        self.assertEqual(result["minutes"], 10)
        self.assertNotIn("self_eval", chat.call_args.args[0])
        self.assertNotIn("rating", chat.call_args.args[0])


class RuntimeCleanupTest(unittest.TestCase):
    def test_removes_nested_history_and_preserves_other_learning_records(self):
        old = {"tutoring_self_ratings": {"kp": 5}, "tutoring_order": ["kp"],
               "tutoring_planned_minutes": 10, "tutoring_stars": {"kp": 2},
               "report": {"knowledge_points": [{"self_rating": 5, "system_stars": 2}]},
               "messages": [{"text": "保留聊天"}]}
        expected = without_self_assessment(old)
        self.assertEqual(expected["report"]["knowledge_points"], [{"system_stars": 2}])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("sessions", "integration"):
                (root / name).mkdir()
                (root / name / "sample.json").write_text(json.dumps(old), encoding="utf-8")
            self.assertEqual(clean_runtime(root), (2, 0))
            self.assertEqual(clean_runtime(root), (0, 0))
            self.assertEqual(json.loads((root / "sessions/sample.json").read_text(encoding="utf-8")), expected)


if __name__ == "__main__":
    unittest.main()
