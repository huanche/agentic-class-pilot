"""辅导导航：推进一次后直接交付新题，不让回复再请求同一次切换的确认。"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))
import agent


class TutoringNavigationReplyTests(unittest.TestCase):
    now = "2026-10-21T12:00:00+00:00"
    titles = {"nav-kp-1": "交换基本概念", "nav-kp-2": "点对点通信与全互连问题",
              "nav-kp-3": "交换机的必备功能"}

    def setUp(self):
        agent.register_kp_titles(self.titles)
        self.state = agent.initial_state("navigation-reply-test", "test-student", "test-lesson")
        self.state.update({
            "host_phase": "tutoring", "lesson_status": "running", "now": self.now,
            "stage_started_at": self.now, "lesson_started_at": self.now,
            "lesson_plan": {"source": "platform-published", "title": "交换原理",
                            "knowledge_points": [{"id": k, "title": v} for k, v in self.titles.items()],
                            "segments": []},
            "tutoring_order": list(self.titles), "tutoring_cursor": 0,
            "tutoring_active_kp": "nav-kp-1",
            "tutoring_question": {"kp_id": "nav-kp-1", "question": "请解释交换基本概念。"},
        })
        self.graph = agent.build_graph()

    def turn(self, message):
        self.state = agent.run_turn_stateless(self.graph, self.state, self.now, message, "student")
        return self.state

    def test_navigation_commits_once_and_cannot_be_rephrased_as_a_confirmation(self):
        """即使模型试图回复“要接着往下走吗”，已执行的导航也必须使用确定性回复。"""
        misleading = "按顺序下一个是点对点通信与全互连问题。要接着往下走吗？"
        with mock.patch.object(agent, "llm_available", return_value=True), \
                mock.patch.object(agent, "_tutoring_pick_question", return_value=("检测：请解释全互连的线路数。", True)), \
                mock.patch.object(agent, "llm_polish", return_value=misleading) as polish, \
                mock.patch.object(agent, "_tutoring_judge", return_value=("unclear", "", {})):
            state = self.turn("下一个知识点")
            public = agent.tutoring_public(state, self.now)
            self.assertEqual(public["current_no"], 2)
            self.assertEqual(public["question"]["kp_no"], 2)
            self.assertIn("点对点通信与全互连问题", state["reply_text"])
            self.assertIn(public["question"]["text"], state["reply_text"])
            self.assertNotIn("要接着往下走吗", state["reply_text"])
            polish.assert_not_called()

            # 普通回应不会再跳；再次明确要求下一个，才允许继续到第3项。
            self.turn("好")
            self.assertEqual(agent.tutoring_public(self.state, self.now)["current_no"], 2)
            self.turn("下一个知识点")
            self.assertEqual(agent.tutoring_public(self.state, self.now)["current_no"], 3)

    def test_model_recognized_skip_also_delivers_the_committed_question(self):
        """非正则表达经模型识别为skip后，同样不再请求确认。"""
        with mock.patch.object(agent, "llm_available", return_value=True), \
                mock.patch.object(agent, "_tutoring_judge", return_value=("not_answer", "", {"intent": "skip"})), \
                mock.patch.object(agent, "_tutoring_pick_question", return_value=("新的检测题", True)), \
                mock.patch.object(agent, "llm_polish", return_value="要接着往下走吗？") as polish:
            state = self.turn("这部分先放一放")
            self.assertEqual(agent.tutoring_public(state, self.now)["current_no"], 2)
            self.assertIn("新的检测题", state["reply_text"])
            polish.assert_not_called()

    def test_end_of_catalog_is_not_rephrased_as_another_switch(self):
        self.state["tutoring_cursor"] = 2
        self.state["tutoring_active_kp"] = "nav-kp-3"
        self.state["tutoring_question"] = {"kp_id": "nav-kp-3", "question": "末题"}
        with mock.patch.object(agent, "llm_available", return_value=True), \
                mock.patch.object(agent, "llm_polish", return_value="要接着往下走吗？") as polish:
            state = self.turn("下一个知识点")
            self.assertIn("都过完", state["reply_text"])
            self.assertIsNone(state["tutoring_question"])
            self.assertEqual(state["host_phase"], "tutoring")
            polish.assert_not_called()

    def test_skip_without_pending_question_uses_the_same_committed_reply(self):
        """无挂起题时由独立分类器识别导航，也直接交付新题。"""
        self.state["tutoring_question"] = None
        with mock.patch.object(agent, "llm_available", return_value=True), \
                mock.patch.object(agent, "_tutoring_classify_message", return_value={"intent": "skip"}), \
                mock.patch.object(agent, "_tutoring_pick_question", return_value=("新知识点的检测题", True)), \
                mock.patch.object(agent, "llm_polish", return_value="要继续吗？") as polish:
            state = self.turn("这部分先放一放")
            self.assertEqual(agent.tutoring_public(state, self.now)["current_no"], 2)
            self.assertIn("新知识点的检测题", state["reply_text"])
            polish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
