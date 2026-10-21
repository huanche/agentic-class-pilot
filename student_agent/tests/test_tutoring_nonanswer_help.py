"""不知道/答不上来必须留在当前知识点先讲解，不能被模型判对或判成跳过。"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))
import agent


class TutoringNonanswerHelpTests(unittest.TestCase):
    now = "2026-10-21T12:00:00+00:00"
    concept = "n个终端全互连需要n(n-1)/2对线路，使用交换设备可减少用户之间的直接连接。"

    def setUp(self):
        self.titles = {"help-kp-1": "交换概念", "help-kp-2": "全互连问题", "help-kp-3": "交换机功能"}
        agent.register_kp_titles(self.titles)
        self.state = agent.initial_state("nonanswer-help-test", "test-student", "test-lesson")
        self.state.update({
            "host_phase": "tutoring", "lesson_status": "running", "now": self.now,
            "stage_started_at": self.now, "lesson_started_at": self.now,
            "lesson_plan": {"source": "platform-published", "title": "交换原理", "segments": [],
                            "knowledge_points": [{"id": k, "title": v,
                                                  "expected": [self.concept] if k == "help-kp-2" else []}
                                                 for k, v in self.titles.items()]},
            "tutoring_order": list(self.titles), "tutoring_cursor": 1,
            "tutoring_active_kp": "help-kp-2", "kp_stars": {"help-kp-2": 2},
            "tutoring_question": {"kp_id": "help-kp-2", "question": "为什么终端增多时全互连不可行？",
                                  "hint_given": False, "kind": "basic", "was_fresh": True},
        })
        self.graph = agent.build_graph()

    def turn(self, message):
        self.state = agent.run_turn_stateless(self.graph, self.state, self.now, message, "student")
        return self.state

    def assert_still_learning_current_point(self, state):
        public = agent.tutoring_public(state, self.now)
        self.assertEqual(public["current_no"], 2)
        self.assertEqual(public["question"]["kp_no"], 2)
        self.assertTrue(public["question"]["hint_given"])
        self.assertEqual(state["kp_stars"].get("help-kp-2"), 2)
        self.assertFalse(state.get("tutoring_stats"))
        self.assertFalse(state.get("mastery_updates"))

    def test_nonanswers_bypass_even_an_incorrect_model_judgement(self):
        for phrase in ("不知道", "我不知道", "不知道。", "不知道？", "我不清楚", "想不起来了", "答不上来",
                       "不会", "不太会", "没思路", "不知道下一步怎么回答"):
            for verdict in (("correct", "答对了", {"performance": "understood", "note": "错误的模型判断"}),
                            ("not_answer", "", {"intent": "skip"})):
                with self.subTest(phrase=phrase, verdict=verdict[0]):
                    self.setUp()
                    with mock.patch.object(agent, "llm_available", return_value=True), \
                            mock.patch.object(agent, "_tutoring_judge", return_value=verdict) as judge, \
                            mock.patch.object(agent, "_tutoring_pick_question", return_value=("不应出现的下一题", True)) as pick, \
                            mock.patch.object(agent, "llm_polish", return_value="先讲清楚全互连：每对终端都要连接，线路数会快速增加。"):
                        state = self.turn(phrase)
                        self.assert_still_learning_current_point(state)
                        judge.assert_not_called()
                        pick.assert_not_called()

    def test_no_model_still_explains_using_published_points(self):
        with mock.patch.object(agent, "llm_available", return_value=False):
            state = self.turn("不知道")
        self.assert_still_learning_current_point(state)
        self.assertIn(self.concept, state["reply_text"])
        self.assertIn("全互连问题", state["reply_text"])

    def test_explicit_skip_after_not_knowing_is_still_respected(self):
        with mock.patch.object(agent, "llm_available", return_value=False), \
                mock.patch.object(agent, "_tutoring_pick_question", return_value=("交换机功能新题", True)):
            state = self.turn("不知道，这题跳过吧，下一个知识点")
        self.assertEqual(agent.tutoring_public(state, self.now)["current_no"], 3)

    def test_correct_answer_after_explanation_is_assessed_as_hinted(self):
        with mock.patch.object(agent, "llm_available", return_value=False):
            self.turn("不知道")
        with mock.patch.object(agent, "llm_available", return_value=True), \
                mock.patch.object(agent, "_tutoring_judge", return_value=(
                    "correct", "", {"performance": "understood", "note": "提示后解释了线路随终端数增加"})), \
                mock.patch.object(agent, "_tutoring_pick_question", return_value=("下一知识点的题", True)), \
                mock.patch.object(agent, "llm_polish", return_value="理解了，我们继续。"):
            state = self.turn("每对终端都要连接，线路数按n(n-1)/2增加。")
        self.assertEqual(state["kp_stars"]["help-kp-2"], 3)
        self.assertEqual(state["tutoring_stats"]["hinted_correct"], 1)
        self.assertEqual(agent.tutoring_public(state, self.now)["current_no"], 3)


if __name__ == "__main__":
    unittest.main()
