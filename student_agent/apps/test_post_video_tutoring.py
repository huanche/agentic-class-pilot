"""工单 01（最小闭环）的缝 A 回归：视频完 → 自动进入「课后辅导」。

关掉模型跑（AGENT_LLM_API_KEY=""）：开场消息的骨架是确定性的
（知识点编号列表来自课时/知识库），直接断言内容；需要验证
「LLM 只润色」契约的用例再用 mock 桩。
"""

from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timedelta
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

    def test_video_skip_flag_default_off_env_on(self) -> None:
        """本地测试开关（工单 07）：默认关，env 开。"""
        self._begin_demo_lesson()
        state = self.client.get(f"/api/session/{self.sid}/state").json()
        self.assertFalse(state["video_skip_allowed"])
        with mock.patch.dict(os.environ, {"AGENT_ALLOW_VIDEO_SKIP": "true"}):
            state2 = self.client.get(f"/api/session/{self.sid}/state").json()
        self.assertTrue(state2["video_skip_allowed"])

    def test_switch_off_restores_recap_orchestration(self) -> None:
        with tutoring_off():
            self._begin_demo_lesson()
            done = self.client.post(f"/api/session/{self.sid}/media/done", json={})
            state = self.client.get(f"/api/session/{self.sid}/state").json()

        self.assertEqual(done.json()["phase"], "recap_discussion")
        self.assertIn("deep_inquiry", state["remaining_stages"])
        self.assertIn("class_discussion", state["remaining_stages"])

    # ── 骨架出结构、LLM 只润色 ────────────────────────────

    def test_opening_is_skeleton_only_even_with_model(self) -> None:
        """开场骨架即全文：即使接了模型也**不调用**——「视频完→辅导」的
        切换不能被模型延迟拖慢（实测润色要 20–35 秒）。模型从学生
        第一条消息开始参与。"""
        self._begin_demo_lesson()

        calls: list = []

        def fake_chat(system: str, user: str):
            calls.append(system)
            return "润色结果"

        with mock.patch.object(agent, "llm_available", return_value=True), \
                mock.patch.object(agent, "llm_chat", side_effect=fake_chat):
            done = self.client.post(f"/api/session/{self.sid}/media/done", json={})

        self.assertEqual(done.json()["phase"], "tutoring")
        self.assertEqual(calls, [], "切换轮不得调用模型")
        reply = done.json()["reply_text"]
        self.assertIn("1. 调度是什么", reply)
        self.assertIn("顺序", reply)


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


    def test_self_rating_recorded_separately_from_system_stars(self) -> None:
        """「2 我给自己 2 分」：自评按知识点记录，且与系统星级分开存储。"""
        self._enter_tutoring()

        answer = self.client.post(
            f"/api/session/{self.sid}/message",
            json={"text": "2 我给自己 2 分。"},
        )

        self.assertEqual(answer.status_code, 200, answer.text)
        tutoring = self._state()["tutoring"]
        self.assertEqual(tutoring["self_ratings"], {"2": 2})
        # 自评只表达意愿：系统星级（stars）不因此产生任何条目
        self.assertEqual(self._state()["stars"], {})
        # 回复确认记下了自评
        self.assertIn("自评", answer.json()["reply_text"])

    def test_self_rating_with_punctuation(self) -> None:
        """「1，我给自己 3 分」——编号与自评之间有逗号也要解析（真机暴露的缺口）。"""
        self._enter_tutoring()

        self.client.post(
            f"/api/session/{self.sid}/message",
            json={"text": "1，我给自己 3 分。"},
        )

        self.assertEqual(self._state()["tutoring"]["self_ratings"], {"1": 3})


    def test_duration_sets_planned_end_at(self) -> None:
        """「想复习 15 分钟」：从这条消息时刻起算计划结束时间。"""
        self._enter_tutoring()

        answer = self.client.post(
            f"/api/session/{self.sid}/message",
            json={"text": "想复习 15 分钟。"},
        )

        self.assertEqual(answer.status_code, 200, answer.text)
        tutoring = self._state()["tutoring"]
        self.assertEqual(tutoring["planned_minutes"], 15)
        # 服务端时间戳：倒计时只是展示换算，刚说完应剩约 15 分钟
        remaining = tutoring["remaining_seconds"]
        self.assertGreaterEqual(remaining, 870)
        self.assertLessEqual(remaining, 900)
        self.assertIn("15", answer.json()["reply_text"])

    def test_default_duration_applies_at_entry(self) -> None:
        """没报时长：进辅导那一刻按默认时长（15 分钟）起算。"""
        self._enter_tutoring()

        tutoring = self._state()["tutoring"]
        self.assertEqual(tutoring["planned_minutes"], 15)
        self.assertTrue(0 <= tutoring["remaining_seconds"] <= 900)

    def test_default_minutes_configurable(self) -> None:
        """默认规划时长可用环境变量改。"""
        with mock.patch.dict(os.environ, {"AGENT_TUTORING_DEFAULT_MINUTES": "5"}):
            self._enter_tutoring()
            tutoring = self._state()["tutoring"]

        self.assertEqual(tutoring["planned_minutes"], 5)
        self.assertLessEqual(tutoring["remaining_seconds"], 300)


    def _backdate_plan(self, minutes: int) -> None:
        """把已生效的计划结束时间拨回 minutes 分钟前，模拟时间流逝。"""
        s = server.SESSIONS[self.sid]
        s["state"]["tutoring_planned_end_at"] = (
            datetime.now().astimezone() - timedelta(minutes=minutes)
        ).isoformat(timespec="seconds")

    def test_new_duration_resets_planned_end(self) -> None:
        """中途「再复习 10 分钟」：按新消息时刻重设计划结束（不是累加）。"""
        self._enter_tutoring()
        self.client.post(f"/api/session/{self.sid}/message",
                         json={"text": "想复习 15 分钟。"})
        self._backdate_plan(30)

        answer = self.client.post(
            f"/api/session/{self.sid}/message",
            json={"text": "再复习 10 分钟。"},
        )

        tutoring = self._state()["tutoring"]
        self.assertEqual(tutoring["planned_minutes"], 10)
        self.assertTrue(570 <= tutoring["remaining_seconds"] <= 600,
                        tutoring["remaining_seconds"])
        self.assertIn("10", answer.json()["reply_text"])

    def test_time_up_checks_in_but_keeps_session(self) -> None:
        """计划时间到：回复变成到点关照（询问还有没有问题），会话不关。"""
        self._enter_tutoring()
        self._backdate_plan(5)

        answer = self.client.post(
            f"/api/session/{self.sid}/message",
            json={"text": "时间片轮转是什么意思？"},
        )

        state = self._state()
        self.assertEqual(state["phase"], "tutoring")
        self.assertEqual(state["status"], "running")
        self.assertIn("时间差不多到了", answer.json()["reply_text"])

    def test_question_routed_to_help_flow_not_intent_confirm(self) -> None:
        """提问/求助不落进意愿确认模板，走答疑承接并回应学生问的点。"""
        self._enter_tutoring()

        answer = self.client.post(
            f"/api/session/{self.sid}/message",
            json={"text": "我不太懂多级反馈队列，帮我讲讲"},
        )

        reply = answer.json()["reply_text"]
        self.assertIn("多级反馈队列", reply)
        self.assertNotIn("就按你说的来", reply)
        self.assertEqual(self._state()["phase"], "tutoring")

    def test_end_phrasing_ends_tutoring(self) -> None:
        """「今天就到这」= 明确结束（工单 05 已落地）：切到 ending 并有回复。
        反馈入库的完整断言见 TutoringEndFeedbackTest。"""
        self._enter_tutoring()

        answer = self.client.post(
            f"/api/session/{self.sid}/message",
            json={"text": "今天就到这吧。"},
        )

        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertEqual(answer.json()["phase"], "ending")
        self.assertTrue(answer.json()["reply_text"].strip())


class TutoringEvidenceMasteryTest(unittest.TestCase):
    """工单 03（作答证据与星级）的缝 A 回归。

    出题/判答在骨架层：出题确定性（无模型也能问），判答走可 mock 的
    _tutoring_judge（模型给出 correct/wrong/unclear 判定）。
    """

    sid = "test-tutoring-mastery"
    student_id = "test-tutoring-mastery-student"

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

    def _state(self) -> dict:
        return self.client.get(f"/api/session/{self.sid}/state").json()

    def _send(self, text: str):
        return self.client.post(
            f"/api/session/{self.sid}/message", json={"text": text})

    def _kp_id(self, no: int) -> str:
        tutoring = self._state()["tutoring"]
        return next(kp["kp_id"] for kp in tutoring["knowledge_points"]
                    if kp["no"] == no)

    def test_diagnostic_question_asked_and_correct_answer_advances(self) -> None:
        """进入知识点后 AI 摆出检测题；判答为对 → 星级 +1、清题、推进到
        顺序中的下一个知识点并出新题。"""
        self._enter_tutoring()

        # 学生表示就绪（非意愿消息）→ AI 对第一个知识点出检测题
        ready = self._send("那我准备好了")
        self.assertIn("小检测", ready.json()["reply_text"])
        self.assertIn("调度是什么", ready.json()["reply_text"])
        question1 = self._state()["tutoring"]["question"]
        self.assertEqual(question1["kp_no"], 1)
        self.assertFalse(question1["hint_given"])

        # 判答走 mock 的模型：返回 correct
        def fake_chat(system: str, user: str):
            return '{"verdict": "correct", "note": "讲得对"}'

        with mock.patch.object(agent, "llm_available", return_value=True), \
                mock.patch.object(agent, "llm_chat", side_effect=fake_chat):
            judged = self._send("调度就是决定谁先用处理机")

        # 第一个知识点升到 1 星（无提示独立答对）
        self.assertEqual(self._state()["stars"].get(self._kp_id(1)), 1,
                         self._state()["stars"])
        # 清题 + 推进：新题落在顺序中的第二个知识点上
        question2 = self._state()["tutoring"]["question"]
        self.assertEqual(question2["kp_no"], 2)

    def test_wrong_answer_marks_hint_and_keeps_question(self) -> None:
        """判答为错 → 星级不动、不换知识点，题标记为已提示（后续追问）。"""
        self._enter_tutoring()
        self._send("那我准备好了")

        def fake_chat(system: str, user: str):
            return '{"verdict": "wrong", "note": "说反了"}'

        with mock.patch.object(agent, "llm_available", return_value=True), \
                mock.patch.object(agent, "llm_chat", side_effect=fake_chat):
            self._send("调度就是随便乱选")

        state = self._state()
        # 答错不产生星级条目（无证据无条目），等价 0 星
        self.assertEqual(state["stars"].get(self._kp_id(1), 0), 0)
        question = state["tutoring"]["question"]
        self.assertEqual(question["kp_no"], 1)
        self.assertTrue(question["hint_given"])

    def test_non_answer_messages_do_not_touch_stars(self) -> None:
        """追问/求助/意愿类消息不是作答：不出判定、星级不动、题保留。"""
        self._enter_tutoring()
        self._send("那我准备好了")

        self._send("这个知识点能再讲讲吗？")

        state = self._state()
        # 非作答消息不产生星级条目
        self.assertEqual(state["stars"].get(self._kp_id(1), 0), 0)
        question = state["tutoring"]["question"]
        self.assertEqual(question["kp_no"], 1)
        self.assertFalse(question["hint_given"])


    def test_question_and_answer_events_persisted_in_demo_mode(self) -> None:
        """出题与判答都落学习事件：demo 态写 runtime JSON
        （平台态同一份 record_event 代码路径进 learning_events）。"""
        from apps.integration import persistence

        with mock.patch.dict(os.environ, {"STUDENT_DEMO_MODE": "true"}):
            self._enter_tutoring()
            self._send("那我准备好了")

            def fake_chat(system: str, user: str):
                return '{"verdict": "correct", "note": "ok"}'

            with mock.patch.object(agent, "llm_available", return_value=True), \
                    mock.patch.object(agent, "llm_chat", side_effect=fake_chat):
                self._send("调度就是决定谁先用处理机")

        path = persistence.RUNTIME_DIR / f"events-{self.sid}.json"
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        events = json.loads(path.read_text(encoding="utf-8"))
        types = [e["event_type"] for e in events]
        self.assertIn("tutoring_question", types)
        self.assertIn("tutoring_answer", types)

        q = next(e for e in events if e["event_type"] == "tutoring_question")
        self.assertEqual(q["payload"]["kp_id"], self._kp_id(1))
        self.assertIn("小检测", q["payload"]["question"])
        self.assertFalse(q["payload"]["hint_given"])

        a = next(e for e in events if e["event_type"] == "tutoring_answer")
        self.assertEqual(a["payload"]["verdict"], "correct")
        self.assertFalse(a["payload"]["hint_given"])
        self.assertEqual(a["payload"]["stars_after"], 1)


    def _answer_judged(self, verdict: str, text: str = "我的作答") -> None:
        def fake_chat(system: str, user: str):
            return json.dumps({"verdict": verdict, "note": "stub"}, ensure_ascii=False)

        with mock.patch.object(agent, "llm_available", return_value=True), \
                mock.patch.object(agent, "llm_chat", side_effect=fake_chat):
            self._send(text)

    def _seed_stars(self, kp: str, value: int) -> None:
        s = server.SESSIONS[self.sid]
        s["state"]["kp_stars"] = {**s["state"].get("kp_stars", {}), kp: value}

    def _reset_session(self) -> None:
        """子场景间重置会话：同一测试方法里多次「开始上课」会 409。"""
        session = server.SESSIONS.pop(self.sid, None)
        if session:
            session["stop"].set()
        server._path(self.sid).unlink(missing_ok=True)

    def test_five_stars_gate_three_cases(self) -> None:
        """升 5 星必须「未见新题 + 无提示 + 答对」，三种不满足各一例。"""
        # ① 首次见到的题、无提示、答对 → 可升 5
        self._reset_session()
        self._enter_tutoring()
        self._send("那我准备好了")
        kp1 = self._kp_id(1)
        self._seed_stars(kp1, 4)
        self._answer_judged("correct")
        self.assertEqual(self._state()["stars"].get(kp1), 5)

        # ② 见过的题（was_fresh=False）→ 封顶 4
        self._reset_session()
        self._enter_tutoring()
        self._send("那我准备好了")
        kp1 = self._kp_id(1)
        self._seed_stars(kp1, 4)
        server.SESSIONS[self.sid]["state"]["tutoring_question"]["was_fresh"] = False
        self._answer_judged("correct")
        self.assertEqual(self._state()["stars"].get(kp1), 4)

        # ③ 有提示 → 最多 3：已在 3 星时不再升
        self._reset_session()
        self._enter_tutoring()
        self._send("那我准备好了")
        kp1 = self._kp_id(1)
        self._seed_stars(kp1, 3)
        server.SESSIONS[self.sid]["state"]["tutoring_question"]["hint_given"] = True
        self._answer_judged("correct")
        self.assertEqual(self._state()["stars"].get(kp1), 3)

        # ④ 答错 → 不升星
        self._reset_session()
        self._enter_tutoring()
        self._send("那我准备好了")
        kp1 = self._kp_id(1)
        self._seed_stars(kp1, 4)
        self._answer_judged("wrong")
        self.assertEqual(self._state()["stars"].get(kp1), 4)

    def test_default_minutes_reads_rubric_file(self) -> None:
        """默认时长收编进量规配置域：文件值生效，env 仍可覆盖。"""
        rubric_default = agent._tutoring_rubric().get("default_minutes")
        self.assertEqual(rubric_default, 15)
        with mock.patch.dict(os.environ, {"AGENT_TUTORING_DEFAULT_MINUTES": "7"}):
            self.assertEqual(agent.tutoring_default_minutes(), 7)
        self.assertEqual(agent.tutoring_default_minutes(), rubric_default)


    def test_double_wrong_moves_to_fresh_question_same_kp(self) -> None:
        """答错先追问（同题标记提示）；再错则讲解并换**未见新题**（同知识点）。"""
        self._reset_session()
        self._enter_tutoring()
        self._send("那我准备好了")
        q1 = self._state()["tutoring"]["question"]["text"]
        kp1 = self._kp_id(1)

        self._answer_judged("wrong")   # 第一次错：追问，同题
        q_after1 = self._state()["tutoring"]["question"]
        self.assertEqual(q_after1["text"], q1)
        self.assertTrue(q_after1["hint_given"])

        self._answer_judged("wrong")   # 第二次错：换新题
        q2 = self._state()["tutoring"]["question"]
        self.assertEqual(q2["kp_no"], 1)
        self.assertNotEqual(q2["text"], q1)
        self.assertFalse(q2["hint_given"])
        self.assertTrue(q2["was_fresh"])
        self.assertEqual(self._state()["stars"].get(kp1, 0), 0)

    def test_llm_generation_receives_seen_list(self) -> None:
        """接模型时出新题走生成链路：已见题干喂进 prompt 让它避开。"""
        self._reset_session()
        self._enter_tutoring()
        self._send("那我准备好了")
        q1 = self._state()["tutoring"]["question"]["text"]

        captured: dict = {}

        def fake_chat(system: str, user: str):
            if "判定" in system:
                return json.dumps({"verdict": "wrong"}, ensure_ascii=False)
            captured.setdefault("users", []).append(user)
            return "LLM 新题：请举例说明调度决策的三个输入。"

        with mock.patch.object(agent, "llm_available", return_value=True), \
                mock.patch.object(agent, "llm_chat", side_effect=fake_chat):
            self._send("第一次：我觉得是随便挑一个")   # 判错 → 追问（不生成）
            self._send("第二次：还是同一个答案")       # 再错 → 生成新题

        q2 = self._state()["tutoring"]["question"]
        self.assertIn("LLM 新题", q2["text"])
        self.assertTrue(q2["was_fresh"])
        # 已见题干喂给了出题 prompt（收集全部非判答调用，别被润色覆盖）
        self.assertTrue(
            any(q1 in u for u in captured.get("users", [])),
            captured.get("users"))

    def test_exhausted_pool_reuses_without_freshness(self) -> None:
        """确定性题池耗尽后复用旧题：was_fresh=False，升星封顶 4。"""
        self._reset_session()
        self._enter_tutoring()
        self._send("那我准备好了")
        kp1 = self._kp_id(1)
        s = server.SESSIONS[self.sid]["state"]
        # 把整 个题池都标记为已见
        s["tutoring_asked"] = [
            v for v in agent._tutoring_question_pool("调度是什么")
        ]
        s["tutoring_question"] = None
        s["tutoring_cursor"] = 0

        self._send("再考我一个")
        q = self._state()["tutoring"]["question"]
        self.assertFalse(q["was_fresh"])


    def test_skip_phrase_moves_to_next_knowledge_point(self) -> None:
        """「进入下一阶段／下一个」是推进指令：跳到顺序中的下一个知识点
        出新题，而不是被当作当前题的作答去判答（真机暴露的坑）。"""
        self._reset_session()
        self._enter_tutoring()
        self._send("准备好了")
        self.assertEqual(self._state()["tutoring"]["question"]["kp_no"], 1)

        answer = self._send("进入下一阶段")

        question = self._state()["tutoring"]["question"]
        self.assertEqual(question["kp_no"], 2, "应跳到第二个知识点")
        self.assertIn("三级调度", answer.json()["reply_text"])
        self.assertFalse(question["hint_given"])

        # 一直跳到最后一个之后再跳 → 收尾提示，不再出题
        for _ in range(5):
            self._send("下一个")
        last = self._send("下一个")
        self.assertIn("都过完", last.json()["reply_text"])
        self.assertIsNone(self._state()["tutoring"]["question"])


class TutoringEndFeedbackTest(unittest.TestCase):
    """工单 05（明确结束与反馈）的缝 A 回归：结束触发、幂等、最新版读取。"""

    sid = "test-tutoring-end"
    student_id = "test-tutoring-end-student"

    def setUp(self) -> None:
        patcher = mock.patch.dict(os.environ, {
            "AGENT_LLM_API_KEY": "", "STUDENT_DEMO_MODE": "true"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(server.app)
        server.SESSIONS.pop(self.sid, None)
        server._path(self.sid).unlink(missing_ok=True)
        from apps.integration import persistence
        for name in ("events", "report-versions"):
            persistence._demo_path(name, self.sid).unlink(missing_ok=True)
            self.addCleanup(persistence._demo_path(name, self.sid).unlink,
                            missing_ok=True)
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

    def _send(self, text: str):
        return self.client.post(
            f"/api/session/{self.sid}/message", json={"text": text})

    def test_explicit_end_generates_versioned_report_once(self) -> None:
        """明确结束 → 生成 v1 反馈（学生视角 + 教师摘要）；重复说不重复入库。"""
        self._enter_tutoring()
        self._send("那我准备好了")

        end = self._send("今天就到这吧")

        self.assertEqual(end.status_code, 200, end.text)
        self.assertEqual(end.json()["phase"], "ending")
        report = self.client.get(f"/api/session/{self.sid}/tutoring-report")
        self.assertEqual(report.status_code, 200, report.text)
        body = report.json()
        self.assertEqual(body["version"], 1)
        payload = body["payload"]
        self.assertEqual(len(payload["knowledge_points"]), 6)
        self.assertEqual(payload["knowledge_points"][0]["system_stars"], 0)
        self.assertEqual(payload["planned_minutes"], 15)
        self.assertTrue(payload["advice"])
        self.assertIn("课后辅导", body["teacher_summary"])
        self.assertIn("unfinished_question", payload)

        # 幂等：已进入 ending 后再说「结束」不产生 v2
        self._send("结束吧")
        again = self.client.get(f"/api/session/{self.sid}/tutoring-report").json()
        self.assertEqual(again["version"], 1)

    def test_report_404_before_any_end(self) -> None:
        self._enter_tutoring()
        r = self.client.get(f"/api/session/{self.sid}/tutoring-report")
        self.assertEqual(r.status_code, 404)


class TutoringResumeTest(unittest.TestCase):
    """工单 06（恢复与续聊）：全链路、重启恢复、换设备同会话、二次结束出 v2。"""

    sid = "test-tutoring-resume"
    student_id = "test-tutoring-resume-student"

    def setUp(self) -> None:
        patcher = mock.patch.dict(os.environ, {
            "AGENT_LLM_API_KEY": "", "STUDENT_DEMO_MODE": "true"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(server.app)
        server.SESSIONS.pop(self.sid, None)
        server._path(self.sid).unlink(missing_ok=True)
        from apps.integration import persistence
        for name in ("events", "report-versions"):
            persistence._demo_path(name, self.sid).unlink(missing_ok=True)
            self.addCleanup(persistence._demo_path(name, self.sid).unlink,
                            missing_ok=True)
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

    def _send(self, text: str):
        return self.client.post(
            f"/api/session/{self.sid}/message", json={"text": text})

    def _state(self) -> dict:
        return self.client.get(f"/api/session/{self.sid}/state").json()

    def _answer_judged(self, verdict: str, text: str = "我的作答") -> None:
        def fake_chat(system: str, user: str):
            if "判定" in system:
                return json.dumps({"verdict": verdict}, ensure_ascii=False)
            if "出" in system:
                return "新题：请再举一个例子说明。"
            return "好的。"

        with mock.patch.object(agent, "llm_available", return_value=True), \
                mock.patch.object(agent, "llm_chat", side_effect=fake_chat):
            self._send(text)

    def _kp_id(self, no: int) -> str:
        tutoring = self._state()["tutoring"]
        return next(kp["kp_id"] for kp in tutoring["knowledge_points"]
                    if kp["no"] == no)

    def test_full_chain_two_versions(self) -> None:
        """视频完→开场→意愿→作答升星→结束 v1→续聊→再作答→再结束 v2。"""
        from apps.integration import persistence

        self._enter_tutoring()
        # 意愿：顺序（先2再1）+ 时长
        self._send("先复习 2，再 1。想复习 15 分钟。")
        # 就绪 → 对顺序第一个知识点（2 号）出题
        self._send("准备好了")
        q1 = self._state()["tutoring"]["question"]
        self.assertEqual(q1["kp_no"], 2)
        # 答对（无提示新题）→ 升星 + 推进到下一个知识点
        self._answer_judged("correct", "三级调度就是高中低三级各管一段")
        self.assertEqual(self._state()["stars"].get(self._kp_id(2)), 1)
        self.assertEqual(self._state()["tutoring"]["question"]["kp_no"], 1)

        # 明确结束 → v1
        end = self._send("今天就到这")
        self.assertEqual(end.json()["phase"], "ending")
        v1 = self.client.get(f"/api/session/{self.sid}/tutoring-report").json()
        self.assertEqual(v1["version"], 1)

        # 继续辅导：回原会话，题和星级都在
        resumed = self.client.post(f"/api/session/{self.sid}/resume-tutoring")
        self.assertEqual(resumed.status_code, 200, resumed.text)
        state = self._state()
        self.assertEqual(state["phase"], "tutoring")
        self.assertEqual(state["tutoring"]["question"]["kp_no"], 1)
        self.assertEqual(state["stars"].get(self._kp_id(2)), 1)
        self.assertTrue(state["tutoring"]["remaining_seconds"] <= 900)

        # 续聊中新的有效作答继续升星，再次明确结束 → v2
        self._answer_judged("correct", "调度就是决定谁先用处理机")
        self.assertEqual(self._state()["stars"].get(self._kp_id(1)), 1)
        self._send("就到这吧")
        v2 = self.client.get(f"/api/session/{self.sid}/tutoring-report").json()
        self.assertEqual(v2["version"], 2)
        self.assertEqual(v2["payload"]["stats"].get("correct"), 2)
        # 旧版可追溯（demo 落盘的版本列表）
        versions = json.loads(
            persistence._demo_path("report-versions", self.sid)
            .read_text(encoding="utf-8"))
        self.assertEqual([v["version"] for v in versions], [1, 2])

    def test_restart_restores_tutoring_with_clock_intact(self) -> None:
        """重启（注册表清空→从磁盘恢复）：阶段/题目/计划时间戳都在，
        剩余时间按服务端时间戳重新换算，不清零。"""
        self._enter_tutoring()
        self._send("准备好了")
        before = self._state()
        planned_end = before["tutoring"]["planned_end_at"]
        question_text = before["tutoring"]["question"]["text"]

        session = server.SESSIONS.pop(self.sid, None)   # 模拟进程重启
        if session:
            session["stop"].set()

        after = self._state()
        self.assertEqual(after["phase"], "tutoring")
        self.assertEqual(after["tutoring"]["question"]["text"], question_text)
        self.assertEqual(after["tutoring"]["planned_end_at"], planned_end)
        self.assertIsNotNone(after["tutoring"]["remaining_seconds"])
        self.assertTrue(after["tutoring"]["remaining_seconds"] <= 900)

    def test_resume_rejected_without_tutoring(self) -> None:
        """没上过辅导的课（老师直接下课）不能恢复。"""
        self._begin_demo_lesson()
        ended = self.client.post(f"/api/session/{self.sid}/end", json={})
        self.assertEqual(ended.status_code, 200, ended.text)

        resumed = self.client.post(f"/api/session/{self.sid}/resume-tutoring")
        self.assertEqual(resumed.status_code, 409)

    def test_platform_sessions_derive_deterministic_sid(self) -> None:
        """平台态：同一（用户,课程,课时）两次进入得到**同一**会话号——
        换设备天然回到原辅导会话。launch/上下文按桩注入。"""
        from apps.integration import course_adapter, launch_context, platform_client
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        lesson_id = course_adapter.from_platform_payload(fixture).lessons[0].id
        payload = {"uid": "u-cross-device", "cid": fixture["courseId"],
                   "rid": "room-1", "pub": {"publicationId": "pub-1", "version": 1}}

        def fake_start(launch_token=None, lesson_id=None, student_id=None):
            return self.client.post("/api/session/start", json={
                "launch_token": "fake.token.sig",
                "lesson_id": lesson_id,
                "student_id": student_id or "ignored",
            })

        with mock.patch.object(launch_context, "verify_launch_token",
                               return_value=payload), \
                mock.patch.object(platform_client, "fetch_learning_context",
                                  return_value=fixture):
            first = fake_start(lesson_id=lesson_id)
            sid1 = first.json()["session_id"]
            server.SESSIONS.pop(sid1, None)   # 换设备：无内存、无 localStorage
            second = fake_start(lesson_id=lesson_id)
            sid2 = second.json()["session_id"]

        self.assertTrue(sid1.startswith("plat-"), sid1)
        self.assertEqual(sid1, sid2, "同一身份+课时必须落回同一会话")
        self.addCleanup(server._path(sid1).unlink, missing_ok=True)
        self.addCleanup(server.SESSIONS.pop, sid1, None)


    def test_order_by_knowledge_point_name(self) -> None:
        """用知识点名字说顺序（「先讲 X 再复习 Y」）也要被遵守。"""
        self._enter_tutoring()

        answer = self._send("先讲时间片轮转与多级反馈队列，再复习调度是什么")

        tutoring = self._state()["tutoring"]
        self.assertEqual(tutoring["order"][0], 6)
        self.assertEqual(tutoring["order"][1], 1)
        # 回复确认从学生点名的知识点开始
        self.assertIn("时间片轮转", answer.json()["reply_text"])

    def test_order_accepts_di_prefix_and_bare_number(self) -> None:
        """「先复习第 2 个」这类写法也要认。"""
        self._enter_tutoring()

        self._send("先复习第 2 个")

        self.assertEqual(self._state()["tutoring"]["order"][0], 2)

    def test_question_mentioning_title_does_not_reorder(self) -> None:
        """提问里带知识点名字不是在定顺序：不得改 order。"""
        self._enter_tutoring()
        self._send("那我准备好了")
        before = self._state()["tutoring"]["order"]

        self._send("三级调度是什么意思？")

        self.assertEqual(self._state()["tutoring"]["order"], before)


class SelfRatingPersistenceTest(unittest.TestCase):
    """工单 03 缝 B：自评与系统星级分开存储、互不冲掉（demo 路径）。"""

    def test_demo_self_rating_persists_alongside_stars(self) -> None:
        from apps.integration import persistence

        with mock.patch.dict(os.environ, {"STUDENT_DEMO_MODE": "true"}):
            key = "test-self-rating-session"
            path = persistence._demo_path("mastery", f"{key}-kp-x")
            self.addCleanup(lambda: path.unlink(missing_ok=True))

            persistence.upsert_self_rating(
                session_key=key, user_id="demo", course_id="c",
                publication_id="p", knowledge_point_id="kp-x", self_rating=4)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["self_rating"], 4)

            # 系统星级写入（判答结果）不冲掉自评；自评写入也不冲星级
            persistence.upsert_mastery(
                session_key=key, user_id="demo", course_id="c",
                publication_id="p", knowledge_point_id="kp-x",
                stars=3, status="理解中")
            data2 = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data2["stars"], 3)
            self.assertEqual(data2["self_rating"], 4)


if __name__ == "__main__":
    unittest.main()
