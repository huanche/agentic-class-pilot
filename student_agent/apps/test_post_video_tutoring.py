"""工单 01（最小闭环）的缝 A 回归：视频完 → 自动进入「课后辅导」。

关掉模型跑（AGENT_LLM_API_KEY=""）：开场消息的骨架是确定性的
（知识点编号列表来自课时/知识库），直接断言内容；需要验证
「LLM 只润色」契约的用例再用 mock 桩。
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from apps import server
from apps.integration import course_adapter
import agent

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" \
    / "platform-learning-context-v1.json"


def tutoring_off():
    """全局开关关闭：回到原有编排（复述→探究→讨论）。"""
    return mock.patch.dict(os.environ, {"AGENT_POST_VIDEO_TUTORING": "0"})


class TutoringFlowTest(unittest.TestCase):
    sid = "test-post-video-tutoring"
    student_id = "test-tutoring-student"

    def setUp(self) -> None:
        # 自带确定性环境：不依赖调用方把 AGENT_LLM_API_KEY 清空，
        # 开场骨架的断言才能稳定。
        patcher = mock.patch.dict(os.environ, {"AGENT_LLM_API_KEY": ""})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(server.app)
        server.SESSIONS.pop(self.sid, None)
        server._path(self.sid).unlink(missing_ok=True)
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        session = server.SESSIONS.pop(self.sid, None)
        if session:
            session["stop"].set()
        server._path(self.sid).unlink(missing_ok=True)

    def _begin_demo_lesson(self) -> None:
        """开一节内置演示课（ch3 处理机调度，video 模式）并按起课铃。"""
        lesson_id = self.client.get(
            "/api/student/courses").json()["courses"][0]["lessons"][0]["lessonId"]
        started = self.client.post("/api/session/start", json={
            "session_id": self.sid, "lesson_id": lesson_id,
            "student_id": self.student_id,
        })
        self.assertEqual(started.status_code, 200, started.text)
        begun = self.client.post(f"/api/session/{self.sid}/begin")
        self.assertEqual(begun.status_code, 200, begun.text)

    # ── 开关开启（默认）：视频完 → 辅导 ────────────────────

    def test_final_media_done_enters_tutoring_with_opening(self) -> None:
        """视频最终播完：不进复述，直接进「课后辅导」；开场消息随本响应自动到达。"""
        self._begin_demo_lesson()

        done = self.client.post(f"/api/session/{self.sid}/media/done", json={})

        self.assertEqual(done.status_code, 200)
        self.assertEqual(done.json()["phase"], "tutoring")
        self.assertEqual(done.json()["status"], "running")
        reply = done.json()["reply_text"]
        # 开场消息要列出本节课知识点的固定数字编号（标题来自 KNOWLEDGE-BASE.md，
        # 是独立于实现的真值来源），并征询复习意愿——全部可省略。
        self.assertIn("1. 调度是什么", reply)
        self.assertIn("2. 三级调度", reply)
        self.assertIn("6. 时间片轮转与多级反馈队列", reply)
        self.assertIn("顺序", reply)
        self.assertIn("星", reply)
        self.assertIn("分钟", reply)

        # 会话状态查询看到的是同一个事实：辅导阶段、课还在上
        state = self.client.get(f"/api/session/{self.sid}/state").json()
        self.assertEqual(state["phase"], "tutoring")
        self.assertEqual(state["status"], "running")

        # 开场消息进了消息流，轮询链路拿得到
        feed = self.client.get(f"/api/session/{self.sid}/messages").json()
        self.assertTrue(any(m["role"] == "teacher" and "1. 调度是什么" in m["text"]
                            for m in feed["messages"]))

    def test_nonfinal_scene_progress_stays_in_video(self) -> None:
        """单页播放进度（final=False）不触发辅导——只有最终完成才进。"""
        self._begin_demo_lesson()

        page = self.client.post(
            f"/api/session/{self.sid}/media/done",
            json={"scene_id": "slide-1", "event_id": "scene-1", "final": False},
        )

        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.json()["phase"], "guided_learning")

    def test_student_message_in_tutoring_gets_reply_and_stays(self) -> None:
        """辅导阶段学生发言：统一消息端点照常工作，阶段不被切走。"""
        self._begin_demo_lesson()
        self.client.post(f"/api/session/{self.sid}/media/done", json={})

        answer = self.client.post(
            f"/api/session/{self.sid}/message",
            json={"text": "先复习 2，我给自己 3 星，复习 15 分钟。"},
        )

        self.assertEqual(answer.status_code, 200)
        self.assertTrue(answer.json()["reply_text"].strip(), "辅导阶段不能对学生的话沉默")
        self.assertEqual(answer.json()["phase"], "tutoring")
        self.assertEqual(answer.json()["status"], "running")

    def test_tutoring_is_not_kicked_out_by_time_budget(self) -> None:
        """辅导阶段没有时间出口：哪怕远超任何预算，心跳也不把学生踢出会话。"""
        self._begin_demo_lesson()
        self.client.post(f"/api/session/{self.sid}/media/done", json={})

        # 把阶段开始时间拨回 30 分钟前，模拟一节上了很久的辅导
        s = server.SESSIONS[self.sid]
        s["state"]["stage_started_at"] = "2026-01-01T00:00:00+08:00"
        s["state"]["lesson_started_at"] = "2026-01-01T00:00:00+08:00"

        st = server._step(self.sid, "", "host", tick_only=True)

        self.assertEqual(st["host_phase"], "tutoring")
        self.assertEqual(st["lesson_status"], "running")

    def test_ended_session_rejects_media_done(self) -> None:
        """下课后的会话不再接受 media/done——课后页"再看一遍"的回放
        即使误报完成，也动不了已经结束的辅导会话。"""
        self._begin_demo_lesson()
        self.client.post(f"/api/session/{self.sid}/media/done", json={})
        self.client.post(f"/api/session/{self.sid}/end", json={})

        replay = self.client.post(f"/api/session/{self.sid}/media/done", json={})

        self.assertEqual(replay.status_code, 409)

    # ── 开关关闭：回到原有编排 ────────────────────────────

    def test_switch_off_restores_recap_orchestration(self) -> None:
        with tutoring_off():
            self._begin_demo_lesson()
            done = self.client.post(f"/api/session/{self.sid}/media/done", json={})
            state = self.client.get(f"/api/session/{self.sid}/state").json()

        self.assertEqual(done.json()["phase"], "recap_discussion")
        self.assertIn("deep_inquiry", state["remaining_stages"])
        self.assertIn("class_discussion", state["remaining_stages"])

    # ── 骨架出结构、LLM 只润色 ────────────────────────────

    def test_opening_structure_comes_from_skeleton_llm_only_polishes(self) -> None:
        """接上模型时：编号列表等结构由骨架决定后交给模型润色；
        模型收到完整结构，返回什么学生就看什么（不叠加工）。"""
        self._begin_demo_lesson()

        captured: dict = {}

        def fake_chat(system: str, user: str):
            captured["system"] = system
            captured["user"] = user
            return "同学你好，视频看完啦！咱们把这节课的知识点过一遍：1. 调度是什么 ……"

        with mock.patch.object(agent, "llm_available", return_value=True), \
                mock.patch.object(agent, "llm_chat", side_effect=fake_chat):
            done = self.client.post(f"/api/session/{self.sid}/media/done", json={})

        self.assertEqual(done.json()["phase"], "tutoring")
        self.assertTrue(captured, "模型可用时开场应走润色链路")
        # 模型拿到的是骨架算好的完整结构（编号 + 标题），不是让它自己编知识点
        self.assertIn("1. 调度是什么", captured["user"])
        self.assertIn("6. 时间片轮转与多级反馈队列", captured["user"])
        self.assertIn("顺序", captured["user"])
        # 润色结果原样到达学生，不与骨架文案拼接
        self.assertEqual(done.json()["reply_text"],
                         "同学你好，视频看完啦！咱们把这节课的知识点过一遍：1. 调度是什么 ……")


class PlatformPlanTutoringTest(unittest.TestCase):
    """平台态：learning_context 生成的已发布计划同样被开关改向。

    平台链路无法在缝 A 直接伪造（launch_token 要真平台），这里用
    tests/fixtures 的契约样例驱动**同一个图**（会话层每轮跑的就是它），
    验证 load_plan 对平台计划也把复述/探究换成了辅导。
    """

    def test_platform_plan_redirects_to_tutoring(self) -> None:
        patcher = mock.patch.dict(os.environ, {"AGENT_LLM_API_KEY": ""})
        patcher.start()
        self.addCleanup(patcher.stop)

        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        context = course_adapter.from_platform_payload(payload)
        graph = agent.build_graph()
        state = agent.initial_state("test-tutoring-platform", "u1", context.lessons[0].id)
        state["learning_context"] = context.model_dump()

        begun = agent.run_turn_stateless(
            graph, state, "2026-10-20T10:00:00+08:00", "", "host",
            external_event=agent.EVENT_BEGIN)
        self.assertEqual(begun["host_phase"], "guided_learning")

        done = agent.run_turn_stateless(
            graph, begun, "2026-10-20T10:01:00+08:00", "", "host",
            external_event=agent.EVENT_MEDIA_DONE)

        self.assertEqual(done["host_phase"], "tutoring")
        self.assertEqual(done["remaining_stages"], [])
        # 开场列出的是**平台下发**的知识点标题，不是本地旧课时的目录
        self.assertIn("1. 心理沙盘游戏初识", done["reply_text"])


class TutoringIntentTimeTest(unittest.TestCase):
    """工单 02（意愿与时间预算）的缝 A 回归。

    关掉模型跑：意愿解析是确定性骨架层，直接断言记录与回复结构。
    """

    sid = "test-tutoring-intent"
    student_id = "test-tutoring-intent-student"

    def setUp(self) -> None:
        patcher = mock.patch.dict(os.environ, {"AGENT_LLM_API_KEY": ""})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(server.app)
        server.SESSIONS.pop(self.sid, None)
        server._path(self.sid).unlink(missing_ok=True)
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        session = server.SESSIONS.pop(self.sid, None)
        if session:
            session["stop"].set()
        server._path(self.sid).unlink(missing_ok=True)

    def _begin_demo_lesson(self) -> None:
        lesson_id = self.client.get(
            "/api/student/courses").json()["courses"][0]["lessons"][0]["lessonId"]
        started = self.client.post("/api/session/start", json={
            "session_id": self.sid, "lesson_id": lesson_id,
            "student_id": self.student_id,
        })
        self.assertEqual(started.status_code, 200, started.text)
        begun = self.client.post(f"/api/session/{self.sid}/begin")
        self.assertEqual(begun.status_code, 200, begun.text)

    def _enter_tutoring(self) -> None:
        self._begin_demo_lesson()
        done = self.client.post(f"/api/session/{self.sid}/media/done", json={})
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(done.json()["phase"], "tutoring")

    def _state(self) -> dict:
        return self.client.get(f"/api/session/{self.sid}/state").json()

    def test_student_order_is_respected_and_recorded(self) -> None:
        """学生指定「先 2 再 1」：顺序被记录（其余按目录补齐），
        回复确认从学生选的第一个知识点开始。"""
        self._enter_tutoring()

        answer = self.client.post(
            f"/api/session/{self.sid}/message",
            json={"text": "先复习 2，再 1。"},
        )

        self.assertEqual(answer.status_code, 200, answer.text)
        tutoring = self._state()["tutoring"]
        # 固定编号目录：ch3 演示课共 6 个知识点
        self.assertEqual([kp["no"] for kp in tutoring["knowledge_points"]],
                         [1, 2, 3, 4, 5, 6])
        # 学生指定的在前，没提的按目录顺序补后
        self.assertEqual(tutoring["order"], [2, 1, 3, 4, 5, 6])
        # 回复从学生选的第一个（2 = 三级调度）开始辅导
        self.assertIn("三级调度", answer.json()["reply_text"])
        self.assertNotIn("我们先从「调度是什么」", answer.json()["reply_text"])


if __name__ == "__main__":
    unittest.main()
