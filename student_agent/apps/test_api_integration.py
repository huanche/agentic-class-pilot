"""统一学生端接口的最小回归测试。"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from apps import server
import agent


class StudentApiIntegrationTest(unittest.TestCase):
    sid = "test-student-api-integration"

    def setUp(self) -> None:
        self.client = TestClient(server.app)
        server.SESSIONS.pop(self.sid, None)
        server._path(self.sid).unlink(missing_ok=True)

    def tearDown(self) -> None:
        session = server.SESSIONS.pop(self.sid, None)
        if session:
            session["stop"].set()
        server._path(self.sid).unlink(missing_ok=True)

    def test_resources_and_single_ai_message_flow(self) -> None:
        courses = self.client.get("/api/student/courses")
        self.assertEqual(courses.status_code, 200)
        lesson_id = courses.json()["courses"][0]["lessons"][0]["lessonId"]

        lesson = self.client.get("/api/lesson", params={"lessonId": lesson_id})
        self.assertEqual(lesson.status_code, 200)
        self.assertGreater(lesson.json()["lesson"]["segmentCount"], 0)

        payload = {"session_id": self.sid, "lesson_id": lesson_id}
        first = self.client.post("/api/session/start", json=payload)
        self.assertEqual(first.json()["status"], "idle")

        begun = self.client.post(f"/api/session/{self.sid}/begin")
        self.assertEqual(begun.status_code, 200)
        self.assertEqual(begun.json()["status"], "running")

        repeated = self.client.post("/api/session/start", json=payload)
        self.assertEqual(repeated.json()["status"], "running")
        self.assertEqual(repeated.json()["phase"], begun.json()["phase"])

        media = self.client.post(f"/api/session/{self.sid}/media/done", json={})
        self.assertEqual(media.status_code, 200)
        self.assertEqual(media.json()["phase"], "recap_discussion")
        state = self.client.get(f"/api/session/{self.sid}/state").json()
        self.assertIn("class_discussion", state["remaining_stages"])

        answer = self.client.post(
            f"/api/session/{self.sid}/message",
            json={"text": "调度负责在多个就绪进程之间分配 CPU，并决定运行多久。"},
        )
        self.assertEqual(answer.status_code, 200)
        self.assertIn("reply_text", answer.json())
        self.assertEqual(answer.json()["phase"], "recap_discussion")
        self.assertEqual(answer.json()["status"], "running")

        deep = self.client.post(f"/api/session/{self.sid}/stage/next")
        self.assertEqual(deep.json()["phase"], "deep_inquiry")
        discussion = self.client.post(f"/api/session/{self.sid}/stage/next")
        self.assertEqual(discussion.json()["phase"], "class_discussion")
        discussion_reply = self.client.post(
            f"/api/session/{self.sid}/message",
            json={"text": "我认为时间片轮转更重视交互任务的响应速度。"},
        )
        self.assertEqual(discussion_reply.json()["phase"], "class_discussion")
        self.assertEqual(discussion_reply.json()["status"], "running")

    def test_a_stopped_session_is_not_written_back(self) -> None:
        """停课之后，正在跑的那一轮不能把会话再落盘一次。

        实测过这个 bug：DELETE 把 ended 写进去之后，一个正好跑在模型调用里的
        心跳轮次结束时会用 running 盖回去 —— 于是停课被静默撤销，进程重启后
        _restore 看到 running 还会把这节课接着上。
        接入真实大模型后一轮要好几秒，这个窗口很容易撞上（本地跑测试时
        tearDown 删掉的会话文件三秒后自己长了回来）。
        """
        lesson_id = self.client.get("/api/student/courses").json()["courses"][0]["lessons"][0]["lessonId"]
        self.client.post("/api/session/start", json={
            "session_id": self.sid, "lesson_id": lesson_id})
        self.client.post(f"/api/session/{self.sid}/begin")
        self.client.delete(f"/api/session/{self.sid}")

        before = server._path(self.sid).read_text(encoding="utf-8")
        self.assertEqual(json.loads(before)["lesson_status"], "ended")

        # 等价于「那个在飞的心跳轮次跑完了」
        server._step(self.sid, "", "host", tick_only=True)

        after = server._path(self.sid).read_text(encoding="utf-8")
        self.assertEqual(after, before, "停掉的会话又被落盘了一次")

    def test_rejects_unsafe_session_id(self) -> None:
        """session_id 会被拼进文件名，路径穿越必须被挡住。

        实测过（加校验之前）：传 "../../pwned" 会 200 并把 json 写到仓库根目录，
        而且这个接口不需要任何凭证。
        """
        for bad in ("../../pwned", "../evil", "a/b", "..", ".hidden", "C:foo"):
            with self.subTest(bad):
                response = self.client.post("/api/session/start", json={
                    "session_id": bad, "lesson_id": "ch3-process-scheduling",
                })
                self.assertEqual(response.status_code, 400)
        self.assertFalse((agent.ROOT / "pwned.json").exists())
        self.assertFalse((agent.ROOT.parent / "pwned.json").exists())
        self.assertFalse((agent.ROOT / "evil.json").exists())


class TeacherLessonApiTest(unittest.TestCase):
    """老师上传课时定义，以及知识点是否真的进了模型上下文。"""

    sid = "test-teacher-lesson-api"
    lesson_id = "test-uploaded-lesson"
    legacy_lesson_id = "ch3-process-scheduling"
    # 用自己的学生号：掌握档案是**按学生**持久化的，跟着 student-001 跑会把
    # 测试用的 KP-901 写进开发机上的真实档案里，冒烟测试的下课总结都能看到它。
    student_id = "test-teacher-lesson-student"

    def setUp(self) -> None:
        self.client = TestClient(server.app)
        server.SESSIONS.pop(self.sid, None)
        server._path(self.sid).unlink(missing_ok=True)
        self._lesson_path().unlink(missing_ok=True)

    def tearDown(self) -> None:
        session = server.SESSIONS.pop(self.sid, None)
        if session:
            session["stop"].set()
        server._path(self.sid).unlink(missing_ok=True)
        self._lesson_path().unlink(missing_ok=True)
        shutil.rmtree(self._student_dir(), ignore_errors=True)

    def _lesson_path(self):
        return agent.LESSONS_DIR / f"{self.lesson_id}.json"

    def _student_dir(self):
        return agent.ROOT / "runtime" / "students" / self.student_id

    def _start_and_begin(self, lesson_id: str):
        """开课并起课铃，用本测试自己的学生号。"""
        started = self.client.post("/api/session/start", json={
            "session_id": self.sid, "lesson_id": lesson_id,
            "student_id": self.student_id,
        })
        self.assertEqual(started.status_code, 200, started.text)
        return self.client.post(f"/api/session/{self.sid}/begin")

    def _payload(self) -> dict:
        return {
            "lesson_id": self.lesson_id,
            "lesson_title": "第9章 测试课时",
            "course_id": "os-test",
            "course": "测试课",
            "chapter": "第 9 周",
            "week": 9,
            "course_summary": "测试课程简介",
            "total_minutes": 30,
            "stages": [
                {"id": "guided_learning", "enabled": True, "minutes": 20,
                 "advance_when": "either"},
                {"id": "recap_discussion", "enabled": True, "minutes": 10,
                 "advance_when": "either"},
            ],
            "knowledge_points": [{
                "kp_id": "KP-901",
                "title": "测试知识点标题",
                "定义": "这是测试用的定义。",
                "检测问题": "测试检测问题？",
            }],
            "segments": [{
                "id": "seg-901", "minutes": 20, "title": "测试段落",
                "knowledge_point_ids": ["KP-901"],
                "knowledge_points": ["测试知识点"],
                "summary": "段落摘要", "content": "段落正文内容。",
            }],
        }

    def _persisted(self) -> dict:
        return json.loads(server._path(self.sid).read_text(encoding="utf-8"))

    def test_upload_readback_and_prompt_injection(self) -> None:
        posted = self.client.post("/api/teacher/lesson", json=self._payload())
        self.assertEqual(posted.status_code, 200, posted.text)
        self.assertTrue(self._lesson_path().is_file())

        got = self.client.get(f"/api/teacher/lesson/{self.lesson_id}")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.json()["lesson"]["knowledge_points"][0]["kp_id"], "KP-901")
        self.assertEqual(got.json()["problems"], [])

        # 出现在课程目录里，且 /api/lesson 能按新课时的 id 取到
        courses = self.client.get("/api/student/courses").json()["courses"]
        listed = [ls["lessonId"] for c in courses for ls in c["lessons"]]
        self.assertIn(self.lesson_id, listed)
        self.assertIn(self.legacy_lesson_id, listed)      # 旧课时没被挤掉
        lesson = self.client.get("/api/lesson", params={"lessonId": self.lesson_id})
        self.assertEqual(lesson.status_code, 200)
        self.assertEqual(lesson.json()["lesson"]["chapter"], "第 9 周")

        # 开课，并确认知识点真的进了装配好的上下文
        begun = self._start_and_begin(self.lesson_id)
        self.assertEqual(begun.status_code, 200, begun.text)

        state = self._persisted()
        self.assertEqual(state["lesson_id"], self.lesson_id)
        context = state.get("assembled_prompt", "")
        self.assertIn("[本课知识点]", context)              # 本功能的核心断言
        self.assertIn("测试知识点标题", context)
        self.assertIn("测试检测问题？", context)
        # 上传的课时不能带上旧课时的知识点目录，否则模型会看到两门课的内容
        self.assertNotIn("调度是什么", context)
        self.assertNotIn("[知识库]", context)

        # active_segment_id 要到 teach 阶段才选定，而 load_context 跑在 teach 之前，
        # 所以 [当前段落] 要到下一轮才装配得出来。再走一轮，验证上传课时的段落
        # （内联在课时文件里，不在 lesson-data/segments/）也能被读到。
        self.client.post(f"/api/session/{self.sid}/message", json={"text": "继续"})
        state = self._persisted()
        self.assertTrue(state.get("active_segment_id"), "讲解阶段应已选定当前段落")
        self.assertIn("段落正文内容。", state.get("assembled_prompt", ""))

    def test_uploaded_lesson_asks_its_own_questions(self) -> None:
        """上传的课时必须问自己的知识点，不能借旧课时的题库。

        runtime/TMISSION.md 与 rules/KNOWLEDGE-BASE.md 写的都是旧课时的内容，
        落回那里就会让学生在被"上"新课的同时被问旧课的问题。
        """
        self.client.post("/api/teacher/lesson", json=self._payload())
        self._start_and_begin(self.lesson_id)
        self.client.post(f"/api/session/{self.sid}/message", json={"text": "继续"})
        self.client.post(f"/api/session/{self.sid}/stage/next")

        state = self._persisted()
        self.assertEqual(state["host_phase"], "recap_discussion")
        queue = state.get("question_queue") or []
        self.assertEqual([q["kp_id"] for q in queue], ["KP-901"])
        self.assertEqual(queue[0]["question"], "测试检测问题？")
        self.assertIn("课时定义", queue[0]["source"])

    def test_background_reaches_the_llm_call(self) -> None:
        """真正的端到端证明：装配好的背景确实进了送给模型的 user message。

        这是本功能的要害所在 —— `assembled_prompt` 以前就是死在这里的：
        load_context 把它拼好了，但没有任何代码读它，模型从来没见过
        [知识库] 那段。只断言 state 里有这个字段证明不了什么，必须抓到实参。
        """
        self.client.post("/api/teacher/lesson", json=self._payload())
        self._start_and_begin(self.lesson_id)

        captured: dict = {}

        def fake_chat(system: str, user: str):
            captured["system"] = system
            captured["user"] = user
            return "好，我们开始看这一段。"

        with mock.patch.object(agent, "llm_available", return_value=True), \
                mock.patch.object(agent, "llm_chat", side_effect=fake_chat):
            self.client.post(f"/api/session/{self.sid}/message",
                             json={"text": "这个知识点是什么意思？"})

        self.assertTrue(captured, "模型可用时本轮应该调用 llm_chat")
        self.assertIn("【课堂背景】", captured["user"])
        self.assertIn("测试知识点标题", captured["user"])   # 老师传的知识点
        self.assertIn("【本轮指令】", captured["user"])       # 骨架仍然说了算
        # 背景只是参考，不能喧宾夺主 —— 人设里必须写明不要照读
        self.assertIn("不要照读", captured["system"])

    def test_uploaded_lesson_without_kps_borrows_nothing(self) -> None:
        """没配知识点的课也不能去借旧课时的题库 —— "没填"不等于"改问别的课"。"""
        body = self._payload() | {
            "knowledge_points": [],
            "segments": [{"id": "seg-901", "minutes": 20, "title": "测试段落",
                          "content": "段落正文内容。"}],
        }
        self.client.post("/api/teacher/lesson", json=body)
        self._start_and_begin(self.lesson_id)
        self.client.post(f"/api/session/{self.sid}/message", json={"text": "继续"})
        self.client.post(f"/api/session/{self.sid}/stage/next")

        state = self._persisted()
        self.assertEqual(state["host_phase"], "recap_discussion")
        self.assertEqual(state.get("question_queue") or [], [])

    def test_report_uses_teacher_supplied_titles(self) -> None:
        """课后报告要用老师填的 title。

        kp_title 原来只认 KNOWLEDGE-BASE.md，老师传的标题会被忽略，
        报告里就变成 "KP-901（KP-901，★）" 这种重号。
        """
        self.client.post("/api/teacher/lesson", json=self._payload())
        self._start_and_begin(self.lesson_id)
        self.client.post(f"/api/session/{self.sid}/message", json={"text": "继续"})

        report = self.client.get(
            f"/api/session/{self.sid}/export", params={"fmt": "json"}
        ).json()
        titles = {kp["kp_id"]: kp["title"] for kp in report["knowledge_points"]}
        self.assertEqual(titles.get("KP-901"), "测试知识点标题")

    def test_legacy_lesson_has_no_uploaded_block(self) -> None:
        """旧课时没有上传的知识点，不该凭空多出空区块。"""
        self._start_and_begin(self.legacy_lesson_id)
        self.assertNotIn("[本课知识点]", self._persisted()["assembled_prompt"])

    def test_rejects_unsafe_lesson_id(self) -> None:
        for bad in ("../evil", "a/b", "..", "CON"):
            body = self._payload() | {"lesson_id": bad}
            response = self.client.post("/api/teacher/lesson", json=body)
            self.assertEqual(response.status_code, 400, f"{bad} 应被拒绝")
        # 没有任何东西被写到 lessons 目录之外
        self.assertFalse((agent.LESSONS_DIR.parent.parent / "evil.json").exists())

    def test_rejects_invalid_plan(self) -> None:
        cases = [
            ("total_minutes 为 0", self._payload() | {"total_minutes": 0}),
            ("没有段落", self._payload() | {"segments": []}),
            ("没有启用阶段", self._payload() | {"stages": [
                {"id": "guided_learning", "enabled": False, "minutes": 20,
                 "advance_when": "either"}]}),
            ("段落缺 id", self._payload() | {"segments": [
                {"id": "", "minutes": 20}]}),
            ("advance_when 非法", self._payload() | {"stages": [
                {"id": "guided_learning", "enabled": True, "minutes": 20,
                 "advance_when": "nonsense"}]}),
            # 半个 advance_policy 在开课时会被 load_plan 下标取用 → 500，
            # 必须在写盘前拦下
            ("advance_policy 缺键", self._payload() | {
                "advance_policy": {"min_stage_minutes": 1}}),
            ("未知阶段 id", self._payload() | {"stages": [
                {"id": "guided_learn", "enabled": True, "minutes": 20,
                 "advance_when": "either"}]}),
            ("阶段缺 id", self._payload() | {"stages": [
                {"enabled": True, "minutes": 20, "advance_when": "either"}]}),
            ("段落引用未声明的知识点", self._payload() | {"segments": [
                {"id": "seg-901", "minutes": 20,
                 "knowledge_point_ids": ["KP-999"]}]}),
            # minutes 不是数字：裸 list[dict] 时这会一路冲进 validate_plan 的
            # sum() 炸成 500；接成 StageIn 后 pydantic 直接回 422
            ("minutes 不是数字", self._payload() | {"stages": [
                {"id": "guided_learning", "enabled": True, "minutes": "abc",
                 "advance_when": "either"}]}),
            ("stages 不是数组", self._payload() | {"stages": "nope"}),
        ]
        for label, body in cases:
            with self.subTest(label):
                response = self.client.post("/api/teacher/lesson", json=body)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertFalse(self._lesson_path().exists(), "校验失败不该落盘")




class StudentAccountTest(unittest.TestCase):
    """学生自注册 + 课程码加入课程。

    账户表是**持久化**的（runtime/accounts.json），所以每次跑用不重复的学号，
    并在 addCleanup 里把账户和学生目录清掉 —— 否则第二次跑就 409。
    """

    def setUp(self) -> None:
        self.client = TestClient(server.app)
        self.number = f"9{int(time.time() * 1000) % 10 ** 9:09d}"
        self.password = "hunter2"
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        record = server._accounts().get(self.number)
        student_dir = server._account_dir(record["studentId"]) if record else None
        with server._ACCOUNTS_LOCK:
            accounts = server._accounts()
            accounts.pop(self.number, None)
            server._save_accounts(accounts)
        if student_dir:
            shutil.rmtree(student_dir, ignore_errors=True)

    def _register(self, name: str = "测试学生", password: str | None = None):
        return self.client.post("/api/student/register", json={
            "student_number": self.number,
            "name": name,
            "password": self.password if password is None else password,
        })

    def _join_code(self) -> str:
        codes = server._join_codes()
        self.assertTrue(codes, "lesson-data/join-codes.json 应有预置课程码")
        return next(iter(codes.values()))

    # ── 注册 ──────────────────────────────────────────────

    def test_register_signs_in_and_starts_with_no_courses(self) -> None:
        res = self._register()
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["courses"], [])
        self.assertIn(server.STUDENT_COOKIE, self.client.cookies)

        session = self.client.get("/api/student/session").json()
        self.assertTrue(session["authenticated"])
        self.assertEqual(session["student"]["studentNumber"], self.number)

    def test_duplicate_registration_is_rejected(self) -> None:
        self._register()
        again = self._register()
        self.assertEqual(again.status_code, 409)

    def test_short_password_is_rejected(self) -> None:
        res = self._register(password="123")
        self.assertEqual(res.status_code, 400)

    def test_password_is_not_stored_in_clear(self) -> None:
        self._register()
        record = server._accounts()[self.number]
        self.assertNotIn(self.password, json.dumps(record, ensure_ascii=False))
        self.assertNotIn("hash", server._public_student(record))

    # ── 登录 ──────────────────────────────────────────────

    def test_login_with_wrong_password_is_rejected(self) -> None:
        self._register()
        fresh = TestClient(server.app)
        res = fresh.post("/api/student/login", json={
            "student_number": self.number, "password": "wrong-one"})
        self.assertEqual(res.status_code, 401)

    def test_login_with_unknown_number_returns_the_same_message(self) -> None:
        """学号不存在和密码错必须回同一句 —— 否则能拿来枚举注册过的学号。"""
        fresh = TestClient(server.app)
        unknown = fresh.post("/api/student/login", json={
            "student_number": "0000000000", "password": "whatever"})
        self._register()
        wrong = fresh.post("/api/student/login", json={
            "student_number": self.number, "password": "wrong-one"})
        self.assertEqual(unknown.status_code, wrong.status_code)
        self.assertEqual(unknown.json()["detail"], wrong.json()["detail"])

    def test_login_after_logout(self) -> None:
        self._register()
        self.client.post("/api/student/logout")
        self.assertFalse(self.client.get("/api/student/session").json()["authenticated"])

        res = self.client.post("/api/student/login", json={
            "student_number": self.number, "password": self.password})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(self.client.get("/api/student/session").json()["authenticated"])

    def test_forged_cookie_is_rejected(self) -> None:
        """cookie 是 HMAC 签名的，改一个字节就该失效。"""
        self._register()
        student_id = server._accounts()[self.number]["studentId"]
        forged = TestClient(server.app)
        forged.cookies.set(server.STUDENT_COOKIE, f"{student_id}.deadbeef")
        self.assertFalse(forged.get("/api/student/session").json()["authenticated"])

    # ── 加课程 ────────────────────────────────────────────

    def test_join_with_unknown_code_is_rejected(self) -> None:
        self._register()
        res = self.client.post("/api/student/join", json={"code": "ZZZZZZ"})
        self.assertEqual(res.status_code, 404)

    def test_join_needs_a_session(self) -> None:
        anon = TestClient(server.app)
        res = anon.post("/api/student/join", json={"code": self._join_code()})
        self.assertEqual(res.status_code, 401)

    def test_join_enrolls_and_marks_the_course(self) -> None:
        self._register()
        # 加入前：目录里 course 存在但 joined 为假
        before = self.client.get("/api/student/courses").json()["courses"]
        self.assertTrue(before)
        self.assertTrue(all(not c["joined"] for c in before))

        res = self.client.post("/api/student/join", json={"code": self._join_code()})
        self.assertEqual(res.status_code, 200, res.text)
        joined_id = res.json()["courseId"]

        after = self.client.get("/api/student/courses").json()["courses"]
        joined = {c["courseId"]: c["joined"] for c in after}
        self.assertTrue(joined[joined_id])
        self.assertEqual(
            self.client.get("/api/student/session").json()["courses"], [joined_id])

    def test_code_is_case_insensitive(self) -> None:
        self._register()
        res = self.client.post(
            "/api/student/join", json={"code": self._join_code().lower()})
        self.assertEqual(res.status_code, 200, res.text)

    def test_joining_twice_is_idempotent(self) -> None:
        self._register()
        code = self._join_code()
        self.client.post("/api/student/join", json={"code": code})
        again = self.client.post("/api/student/join", json={"code": code})
        self.assertEqual(again.status_code, 200)
        self.assertEqual(len(again.json()["courses"]), 1)


class TeacherCourseCodeTest(unittest.TestCase):
    """老师侧生成课程码。用临时文件，别真写进 lesson-data/join-codes.json。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(
            server, "JOIN_CODES_PATH", Path(self.tmp.name) / "join-codes.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(server.app)

    def _a_course_id(self) -> str:
        courses = self.client.get("/api/student/courses").json()["courses"]
        self.assertTrue(courses)
        return courses[0]["courseId"]

    def test_generates_then_reads_back(self) -> None:
        course_id = self._a_course_id()
        made = self.client.post("/api/teacher/course-code", json={"course_id": course_id})
        self.assertEqual(made.status_code, 200, made.text)
        code = made.json()["code"]
        self.assertEqual(len(code), 6)

        again = self.client.post("/api/teacher/course-code", json={"course_id": course_id})
        self.assertEqual(again.json()["code"], code, "不 regenerate 时应取回同一个码")

        got = self.client.get(f"/api/teacher/course-code/{course_id}")
        self.assertEqual(got.json()["code"], code)

    def test_regenerate_rotates_the_code(self) -> None:
        course_id = self._a_course_id()
        first = self.client.post(
            "/api/teacher/course-code", json={"course_id": course_id}).json()["code"]
        second = self.client.post(
            "/api/teacher/course-code",
            json={"course_id": course_id, "regenerate": True}).json()["code"]
        self.assertNotEqual(first, second)

        # 换了码之后旧码失效
        self.assertIsNone(server._course_for_code(first))

    def test_unknown_course_is_rejected(self) -> None:
        res = self.client.post(
            "/api/teacher/course-code", json={"course_id": "no-such-course"})
        self.assertEqual(res.status_code, 404)

    def test_read_missing_code_is_404(self) -> None:
        self.assertEqual(
            self.client.get(f"/api/teacher/course-code/{self._a_course_id()}").status_code,
            404,
        )

class RecapStrategyTest(unittest.TestCase):
    """复述阶段的状态驱动：同一道题，三种答法，AI 的引导必须明显不同。

    关掉模型跑（AGENT_LLM_API_KEY=""），reply_text 就是确定性骨架拼出来的
    朴素文案 —— 正好能直接断言分层，不用去猜模型会怎么说。
    """

    sid_prefix = "test-recap-strategy"
    student_id = "test-recap-student"
    lesson_id = "ch3-process-scheduling"

    # 内置课时的复述第一题是 KP-002，它的证据表有 3 组（见 EVIDENCE_GROUPS）
    FULL = "高级调度把作业调入内存，低级调度从就绪队列选一个上 CPU，中级调度负责对换和内存平衡"
    PARTIAL = "高级调度把作业调入内存"
    BLANK = "不知道"

    def setUp(self) -> None:
        self.addCleanup(lambda: shutil.rmtree(
            agent.ROOT / "runtime" / "students" / self.student_id, ignore_errors=True))

    def _answer_first_recap_question(
        self, tag: str, answer: str, lesson_id: str | None = None
    ) -> str:
        """起一节新课，走到复述阶段的第一题，用 answer 作答，返回 AI 的回复。"""
        sid = f"{self.sid_prefix}-{tag}"
        server.SESSIONS.pop(sid, None)
        server._path(sid).unlink(missing_ok=True)
        self.addCleanup(lambda: (server.SESSIONS.pop(sid, None),
                                 server._path(sid).unlink(missing_ok=True)))

        client = TestClient(server.app)
        started = client.post("/api/session/start", json={
            "session_id": sid, "lesson_id": lesson_id or self.lesson_id,
            "student_id": self.student_id,
        })
        self.assertEqual(started.status_code, 200, started.text)
        client.post(f"/api/session/{sid}/begin")
        client.post(f"/api/session/{sid}/media/done")

        state = json.loads(server._path(sid).read_text(encoding="utf-8"))
        self.assertEqual(state["host_phase"], "recap_discussion")
        self.assertTrue(state.get("pending_question"), "复述阶段应该已挂起第一题")

        return client.post(
            f"/api/session/{sid}/message", json={"text": answer}).json()["reply_text"]

    def test_clear_answer_gets_praised(self) -> None:
        reply = self._answer_first_recap_question("full", self.FULL)
        self.assertIn("很完整", reply, reply)

    def test_the_three_answers_get_three_different_guides(self) -> None:
        """同一道题，三种答法 → 三种明显不同的引导。

        刻意**不写死具体文案**：复述阶段的脚手架是逐级变化的（见
        `_recap_scaffold`），钉死措辞会让测试变成"一改文案就挂" —— 这一版
        最初就是那么写的，后来脚手架改成递进式，它就假报了两次失败。
        这里钉的是**行为不变式**。
        """
        clear = self._answer_first_recap_question("full", self.FULL)
        partial = self._answer_first_recap_question("partial", self.PARTIAL)
        blank = self._answer_first_recap_question("blank", self.BLANK)

        self.assertIn("很完整", clear, clear)                 # 答完整 → 先肯定
        self.assertNotEqual(partial, blank, "两种没答对的情况该给不同的引导")
        for tag, reply in (("部分", partial), ("不会", blank)):
            self.assertNotIn("很完整", reply, f"{tag} 不该被当成答对")
            self.assertTrue(reply.strip(), f"{tag} 必须给点引导，不能空着")
            # 第一轮引导不能直接把答案念出来
            self.assertNotIn("中级调度", reply, f"{tag} 第一轮就把答案给了")

    def test_kp_without_evidence_table_is_not_treated_as_wrong(self) -> None:
        """没有证据表的知识点，不能按「答错了」处理。

        这是本轮的 bug 修复：老的 else 分支把 `match_evidence` 的 (0, 0)
        和「学生没答上来」混在一起 —— 于是老师上传的课时、以及内置课时里
        没进证据表的 KP，**每个回答都会被当成答错**，AI 一直重复同一句话。
        """
        lesson_id = "test-recap-no-rubric"
        lesson_path = agent.LESSONS_DIR / f"{lesson_id}.json"
        lesson_path.unlink(missing_ok=True)
        self.addCleanup(lambda: lesson_path.unlink(missing_ok=True))

        client = TestClient(server.app)
        posted = client.post("/api/teacher/lesson", json={
            "lesson_id": lesson_id,
            "lesson_title": "第9章 测试课时",
            "total_minutes": 30,
            "stages": [
                {"id": "guided_learning", "enabled": True, "minutes": 20,
                 "advance_when": "either"},
                {"id": "recap_discussion", "enabled": True, "minutes": 10,
                 "advance_when": "either"},
            ],
            # KP-901 不在 EVIDENCE_GROUPS 里 → match_evidence 返回 (0, 0)
            "knowledge_points": [{
                "kp_id": "KP-901", "title": "测试知识点",
                "定义": "D", "检测问题": "这道题有标准答案吗？",
            }],
            "segments": [{
                "id": "seg-901", "minutes": 20, "title": "段落",
                "knowledge_point_ids": ["KP-901"], "knowledge_points": ["k"],
                "content": "段落正文。",
            }],
        })
        self.assertEqual(posted.status_code, 200, posted.text)

        reply = self._answer_first_recap_question(
            "norubric", "我觉得是先把作业调进来", lesson_id=lesson_id)

        self.assertNotIn("再想想", reply, "没有证据表 ≠ 学生答错了")
        self.assertNotIn("还差一点", reply)
        self.assertIn("换个角度", reply, reply)

    def test_guide_action_reaches_the_model(self) -> None:
        """策略表里的「动作」必须真的送进模型 —— 否则这份 skill 又是死的。

        只断言 reply_text 不够：模型关掉时走的是朴素兜底，那条路径根本不经过
        策略表。所以这里把 llm_chat 换掉，**抓送给模型的实参** ——
        和 test_background_reaches_the_llm_call 是同一个套路。
        """
        sid = f"{self.sid_prefix}-directive"
        server.SESSIONS.pop(sid, None)
        server._path(sid).unlink(missing_ok=True)
        self.addCleanup(lambda: (server.SESSIONS.pop(sid, None),
                                 server._path(sid).unlink(missing_ok=True)))

        client = TestClient(server.app)
        client.post("/api/session/start", json={
            "session_id": sid, "lesson_id": self.lesson_id,
            "student_id": self.student_id})
        client.post(f"/api/session/{sid}/begin")
        client.post(f"/api/session/{sid}/media/done")

        captured: dict = {}

        def fake_chat(system: str, user: str):
            captured["user"] = user
            return "好，我们继续。"

        with mock.patch.object(agent, "llm_available", return_value=True),                 mock.patch.object(agent, "llm_chat", side_effect=fake_chat):
            client.post(f"/api/session/{sid}/message", json={"text": self.PARTIAL})

        self.assertTrue(captured, "应该调了模型")
        action = agent.recap_guide()[agent.STATE_PARTIAL]["动作"]
        self.assertIn(action, captured["user"], "策略表的「动作」没进模型")
        self.assertIn("【本轮指令】", captured["user"])



if __name__ == "__main__":
    unittest.main()
