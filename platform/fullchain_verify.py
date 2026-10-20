# -*- coding: utf-8 -*-
"""One-shot full-chain verification: teacher publishes -> student enters.
Talks to the local 8088 gateway only. Prints every step's outcome."""
import json
import re
import sys
import time

import httpx

BASE = "http://localhost:8088"
MAILPIT = "http://localhost:58025/api/v1"
TEACHER = {"email": "teacher01@example.com", "password": "Teacher-2026-verify", "full_name": "验证教师"}
STUDENT = {"email": "student01@example.com", "password": "Student-2026-verify", "full_name": "验证学生"}
CLASSROOM_JSON = r"E:\LMS系统参考\项目\agentic-class-pilot\teacher_agent\data\classrooms\8TAq_acb_r.json"


def step(name, ok, extra=""):
    print(f"{'✓' if ok else '✗'} {name}" + (f"  {extra}" if extra else ""))
    if not ok:
        sys.exit(1)


def mail_code(client, email):
    """Fetch the latest 6-digit verification code from Mailpit."""
    for _ in range(15):
        r = client.get(f"{MAILPIT}/messages", params={"limit": 10})
        for m in r.json().get("messages", []):
            to = ";".join(a.get("Address", "") for a in m.get("To", []))
            if email in to:
                detail = client.get(f"{MAILPIT}/message/{m['ID']}").json()
                body = (detail.get("Text") or "") + (detail.get("HTML") or "")
                match = re.search(r"\b(\d{6})\b", body)
                if match:
                    return match.group(1)
        time.sleep(2)
    return None


def register_and_login(client_seed, user, role):
    """Register via the public flow (email code from Mailpit), then log in."""
    with httpx.Client(base_url=BASE, timeout=30) as c:
        c.post("/api/v1/users/send-verification-code", json={"email": user["email"]})
        code = mail_code(c, user["email"])
        step(f"注册验证码({user['email']})", bool(code))
        r = c.post("/api/v1/users/signup", json={
            "email": user["email"], "password": user["password"],
            "full_name": user["full_name"], "role": role, "code": code})
        already = r.status_code == 400 and "已被注册" in r.text
        step(f"注册{role}账号", r.status_code in (200, 201) or already,
             "(已注册,跳过)" if already else (r.text[:120] if r.status_code >= 400 else ""))
    session = httpx.Client(base_url=BASE, timeout=120, headers={
        "Origin": BASE, "Referer": BASE + "/",})
    r = session.post("/api/v1/login/access-token", data={
        "username": user["email"], "password": user["password"]})
    step(f"登录{role}", r.status_code == 200, user["email"])
    return session


# ── Teacher: publish chain ─────────────────────────────────────────
teacher = register_and_login(httpx, TEACHER, "teacher")

data = json.load(open(CLASSROOM_JSON, encoding="utf-8"))
r = teacher.post("/api/classroom", json={"stage": data["stage"], "scenes": data["scenes"]})
step("上传课堂课件", r.status_code in (200, 201),
     f"classroom={data['stage']['id']} | {r.status_code}: {r.text[:200]}" if r.status_code >= 400 else f"classroom={data['stage']['id']}")

r = teacher.post("/api/course-space", json={"title": "全链路验证课程", "description": "fullscreen 验证"})
step("创建课程", r.status_code in (200, 201), r.text[:160] if r.status_code >= 400 else "")
course_id = r.json().get("course", {}).get("id") if r.status_code < 400 else None
if not course_id:
    course_id = r.json().get("id")
step("拿到课程ID", bool(course_id), course_id)

r = teacher.post(f"/api/course-space/{course_id}/classrooms/attach", json={
    "classroomId": data["stage"]["id"], "title": data["stage"].get("name", "验证课件")})
step("归档课件为产物", r.status_code in (200, 201), r.text[:160] if r.status_code >= 400 else "")
artifact_id = None
if r.status_code < 400:
    payload = r.json()
    artifact_id = (payload.get("artifact") or payload.get("artifacts", [{}])[0] or {}).get("id")
step("拿到产物ID", bool(artifact_id), artifact_id)

r = teacher.patch(f"/api/course-space/{course_id}/artifacts/{artifact_id}", json={"action": "approve"})
step("审批通过", r.status_code == 200, r.text[:120] if r.status_code >= 400 else "")

r = teacher.post(f"/api/course-space/{course_id}/publish", json={})
step("发布课程", r.status_code in (200, 201), r.text[:160] if r.status_code >= 400 else "")

r = teacher.get(f"/api/classes/{course_id}/enrollment")
code = None
if r.status_code == 200:
    code = r.json().get("enrollCode") or r.json().get("code") or r.json().get("class", {}).get("enrollCode")
step("获取选课码", bool(code), f"{r.status_code}: {r.text[:160]}" if not code else code)

# ── Student: join and enter ────────────────────────────────────────
student = register_and_login(httpx, STUDENT, "student")

r = student.post("/api/v1/enrollments/join", json={"code": code})
step("学生加入课程", r.status_code in (200, 201), r.text[:160] if r.status_code >= 400 else "")

r = student.post(f"/api/v1/courses/{course_id}/student-workspace")
step("签发学习入口", r.status_code == 200, r.text[:160] if r.status_code >= 400 else "")
if r.status_code == 200:
    body = r.json()
    print("\n════════ 交付 ════════")
    print("教师账号:", TEACHER["email"], "/", TEACHER["password"])
    print("学生账号:", STUDENT["email"], "/", STUDENT["password"])
    print("选课码:", code)
    print("学生入口(浏览器打开):", body.get("url"))
    print("播放器地址:", body.get("playerUrl"))
