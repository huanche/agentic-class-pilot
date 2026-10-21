"""按表现评星、提示与应用门槛、证据持久化、结束及各接口同源。"""
import json
import unittest
from unittest import mock

from apps import server, test_post_video_tutoring as tutoring_tests
from apps.integration import persistence
from apps.integration.mastery import assessed_stars, record_assessment, normalize_mastery_state
import agent


class MasteryRuleTest(unittest.TestCase):
    def test_performance_levels_and_program_gates(self):
        for verdict, performance, question, reasoning, expected in (
            ("wrong", "incorrect", {}, "", 1),
            ("wrong", "partial", {}, "", 2),
            ("correct", "understood", {"hint_given": True}, "", 3),
            ("correct", "understood", {"kind": "basic"}, "", 4),
            ("correct", "transfer", {"kind": "application", "was_fresh": True}, "学生解释了条件变化", 5),
            ("correct", "transfer", {"kind": "application", "was_fresh": False}, "学生解释了条件变化", 4),
            ("correct", "transfer", {"kind": "application", "was_fresh": True, "hint_given": True}, "理由", 3),
            ("correct", "transfer", {"kind": "basic", "was_fresh": True}, "理由", 4),
            ("correct", "transfer", {"kind": "application", "was_fresh": True}, "", 4),
        ):
            with self.subTest(performance=performance, question=question):
                self.assertEqual(assessed_stars(question, verdict, {
                    "performance": performance, "note": "回答依据", "reasoning": reasoning}), expected)

    def test_invalid_or_missing_evidence_never_scores(self):
        for extra in ({"stars": 5}, {"performance": "understood"},
                      {"performance": "invented", "note": "依据"},
                      {"performance": [], "note": "依据"},
                      {"performance": "incorrect", "note": "依据"}):
            self.assertIsNone(assessed_stars({}, "correct", extra))
        self.assertIsNone(assessed_stars({}, "wrong", {"performance": [], "note": "依据"}))

    def test_repeated_correct_is_not_a_counter_and_wrong_flags_review(self):
        state = {"lesson_plan": {"knowledge_points": [{"id": "kp"}]}, "kp_stars": {}, "host_phase": "tutoring"}
        q = {"kp_id": "kp", "question": "请解释核心", "kind": "basic", "was_fresh": True}
        right = {"performance": "understood", "note": "解释了核心"}
        state.update(record_assessment(state, q, "correct", right, "答案"))
        self.assertEqual(state["kp_stars"]["kp"], 4)
        state.update(record_assessment(state, q, "correct", right, "同样的答案"))
        self.assertEqual(state["kp_stars"]["kp"], 4)
        wrong = {"performance": "incorrect", "note": "将因果说反"}
        state.update(record_assessment(state, q, "wrong", wrong, "错误答案"))
        self.assertEqual(state["mastery_needs_review"], [])
        state.update(record_assessment(state, q, "wrong", wrong, "再次说反"))
        self.assertEqual(state["kp_stars"]["kp"], 4)
        self.assertEqual(state["mastery_needs_review"], ["kp"])
        state.update(record_assessment(state, q, "correct", right, "独立解释清楚"))
        self.assertEqual(state["mastery_needs_review"], [])
        state.update(record_assessment(state, q, "wrong", wrong, "一次错误"))
        state.update(record_assessment(state, {**q, "hint_given": True}, "correct", right, "提示后答对"))
        state.update(record_assessment(state, q, "wrong", wrong, "再次错误"))
        self.assertEqual(state["mastery_needs_review"], [], "有正确回答打断时不算连续错误")

    def test_legacy_state_keeps_one_source_without_adding_scores(self):
        result = normalize_mastery_state({"kp_stars": {"kp": 2}, "tutoring_stars": {"kp": 4}})
        self.assertNotIn("tutoring_stars", result)
        self.assertEqual(result["kp_stars"], {"kp": 2})


class UnifiedMasteryFlowTest(unittest.TestCase):
    sid = "test-unified-mastery"
    student_id = "test-unified-student"
    setUp = tutoring_tests.TutoringEvidenceMasteryTest.setUp
    _cleanup = tutoring_tests.TutoringEvidenceMasteryTest._cleanup
    _begin_demo_lesson = tutoring_tests.TutoringEvidenceMasteryTest._begin_demo_lesson
    _enter_tutoring = tutoring_tests.TutoringEvidenceMasteryTest._enter_tutoring
    _state = tutoring_tests.TutoringEvidenceMasteryTest._state
    _send = tutoring_tests.TutoringEvidenceMasteryTest._send
    _kp_id = tutoring_tests.TutoringEvidenceMasteryTest._kp_id

    def answer(self, verdict="correct", performance="understood"):
        with mock.patch.object(agent, "_tutoring_judge", return_value=(verdict, "依据", {
            "performance": performance, "note": "独立说明关键条件", "reasoning": "说明情境变化的依据"})):
            return self._send("调度负责选择处理机使用者")

    def assert_consistent(self, kid, stars):
        state = self._state()
        self.assertEqual(state["stars"][kid], stars)
        report = self.client.get(f"/api/session/{self.sid}/export?fmt=json").json()
        self.assertEqual(next(k["stars"] for k in report["knowledge_points"] if k["kp_id"] == kid), stars)
        if state["tutoring"]:
            no = next(k["no"] for k in state["tutoring"]["knowledge_points"] if k["kp_id"] == kid)
            self.assertEqual(state["tutoring"]["stars"][str(no)], stars)

    def test_one_source_persists_and_end_never_reassesses(self):
        self._enter_tutoring()
        self._send("准备好了")
        kid = self._kp_id(1)
        self.answer()
        self.assert_consistent(kid, 4)
        st = server.SESSIONS[self.sid]["state"]
        self.assertEqual(st["mastery_updates"][0]["new_stars"], 4)
        self.assertEqual(len(st["mastery_history"]), 1)
        stored = json.loads(persistence._demo_path("mastery", f"{self.sid}-{kid}").read_text(encoding="utf-8"))
        self.addCleanup(persistence._demo_path("mastery", f"{self.sid}-{kid}").unlink, missing_ok=True)
        self.assertEqual(stored["stars"], 4)
        self.assertIn("关键条件", stored["evidence"])

        calls = []
        def chat(system, user):
            calls.append((system, user))
            self.assertNotIn("教学评估助手", system)
            return "本次能解释关键条件，建议继续练习新场景。"
        with mock.patch.object(agent, "llm_available", return_value=True), mock.patch.object(agent, "llm_chat", side_effect=chat):
            ended = self._send("今天就到这")
        self.assertEqual(ended.json()["phase"], "ending")
        self.assertIn("4 星", ended.json()["reply_text"])
        self.assert_consistent(kid, 4)
        feedback = self.client.get(f"/api/session/{self.sid}/tutoring-report").json()["payload"]
        item = next(k for k in feedback["knowledge_points"] if k["kp_id"] == kid)
        self.assertEqual(item["system_stars"], 4)
        self.assertIn("独立说明关键条件", item["evidence"])
        self.assertTrue(any("不得改分或另行评分" in user for _, user in calls))
        self.assertFalse(hasattr(agent, "_assess_mastery_with_llm"))
        self.assertNotIn("tutoring_stars", server._restore(self.sid))

    def test_help_caps_next_answer_and_application_can_reach_five(self):
        self._enter_tutoring()
        self._send("准备好了")
        kid = self._kp_id(1)
        self._send("这个知识点能再解释一下吗？")
        self.assertTrue(self._state()["tutoring"]["question"]["hint_given"])
        self.answer()
        self.assert_consistent(kid, 3)
        self._send("先复习 1")
        self.answer()
        self.assert_consistent(kid, 4)
        self._send("先复习 1")
        question = server.SESSIONS[self.sid]["state"]["tutoring_question"]
        self.assertEqual(question["kind"], "application")
        self.answer(performance="transfer")
        self.assert_consistent(kid, 5)

    def test_malformed_model_assessment_keeps_question_and_score(self):
        self._enter_tutoring()
        self._send("准备好了")
        kid = self._kp_id(1)
        with mock.patch.object(agent, "llm_available", return_value=True), \
                mock.patch.object(agent, "llm_chat", return_value='{"verdict":"correct","stars":5}'):
            self._send("我的答案")
        self.assertEqual(self._state()["stars"].get(kid, 0), 0)
        self.assertEqual(self._state()["tutoring"]["question"]["kp_id"], kid)

    def test_video_and_heartbeat_never_award_stars(self):
        self._enter_tutoring()
        self.assertEqual(self._state()["stars"], {})
        server._step(self.sid, tick_only=True)
        self.assertEqual(self._state()["stars"], {})
        self.assertEqual(server.SESSIONS[self.sid]["state"]["mastery_history"], [])
