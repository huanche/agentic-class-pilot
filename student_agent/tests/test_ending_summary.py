"""下课小结通过消息、状态、落盘恢复和报告保持一致。"""
import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from apps import server
from apps.test_post_video_tutoring import begin_platform_lesson
import agent


class EndingSummaryTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"AGENT_LLM_API_KEY": "", "STUDENT_DEMO_MODE": "true"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(server.app)
        self.sid = begin_platform_lesson(self, "ending-summary")
        self.client.post(f"/api/session/{self.sid}/media/done", json={})

    def test_summary_survives_end_restore_and_report(self):
        response = self.client.post(f"/api/session/{self.sid}/message", json={"text": "今天就到这吧"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["phase"], "ending")
        summary = response.json()["ending_summary"]
        self.assertIn("调度是什么", summary)
        self.assertNotIn("kp-001", summary)
        self.assertIn(summary, response.json()["reply_text"])
        session = server.SESSIONS.pop(self.sid)
        session["stop"].set()
        restored = self.client.get(f"/api/session/{self.sid}/state").json()
        self.assertEqual(restored["ending_summary"], summary)
        report = self.client.get(f"/api/session/{self.sid}/export?fmt=json").json()
        self.assertEqual(report["ending_summary"], summary)
        self.client.post(f"/api/session/{self.sid}/resume-tutoring")
        resumed = self.client.get(f"/api/session/{self.sid}/state").json()
        self.assertEqual(resumed["ending_summary"], "")

    def test_model_summary_is_saved_without_regrading(self):
        with mock.patch.object(agent, "llm_available", return_value=True), \
                mock.patch.object(agent, "llm_chat", side_effect=lambda system, user:
                                  "本节课复习了调度，课后请比较不同调度方式。"
                                  if "正在宣布下课" in system else "好，我们收尾。"):
            response = self.client.post(f"/api/session/{self.sid}/end", json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["ending_summary"].startswith("本节课复习了调度"))
        self.assertTrue(all(value == 0 for value in server.SESSIONS[self.sid]["state"]["kp_stars"].values()))

    def test_legacy_summary_fallback_is_limited_to_ending(self):
        self.assertEqual(server._ending_summary_text({"host_phase": "ending", "reply_text": "旧小结"}), "旧小结")
        self.assertEqual(server._ending_summary_text({"host_phase": "tutoring", "reply_text": "普通回复"}), "")
