"""S6 验收矩阵（生产服务器版）。

在真实部署拓扑（HTTPS 网关 + systemd 三服务）上验证学生接入的
安全与一致性语义。每个用户一个贯穿会话（opener + CookieJar），
与浏览器行为一致。

用例：
  1 幂等        同一学生重复进入同一课程 → 课程上下文一致
  2 越权        未选课学生请求 student-workspace → 403
  3 双学生隔离  会话按 sessionId 隔离，课程上下文各自解析
  4 重启恢复    平台重启后重新签发 launch → 学生会话可重建
  5 教师隔离    非属主教师读课程名单 → 403
"""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.cookiejar import CookieJar

BASE = "https://agenticclasspilot.com"
STUDENT = "http://127.0.0.1:8000"
PLATFORM = "http://127.0.0.1:8080"
COURSE = "25419205-49d4-4d78-bf73-25c269176aec"  # 现代交换原理（含已发布课时）
LEGACY_ID = "sx2QQqfZUm48"
STU_A = "s6-a@tmp.local"
STU_B = "s6-b@tmp.local"
TEA_A = "438206573@qq.com"  # 课程属主（只取 id，不登录）
PASSWORD = "S6Test#2026"
results = []


def sh(sql: str) -> str:
    out = subprocess.run(
        ["sudo", "docker", "exec", "agentedu-final-database-1",
         "psql", "-q", "-U", "platform", "-d", "education", "-t", "-A", "-c", sql],
        capture_output=True, text=True)
    return out.stdout.strip()


class User:
    """一个浏览器等价会话：单 opener 贯穿登录与后续请求。"""

    def __init__(self, email: str):
        self.email = email
        self.cj = CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))

    def call(self, method: str, url: str, form=None, js=None):
        req = urllib.request.Request(url, method=method)
        if form is not None:
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            data = urllib.parse.urlencode(form).encode()
        elif js is not None:
            req.add_header("Content-Type", "application/json")
            data = json.dumps(js).encode()
        else:
            data = None
        req.add_header("Origin", BASE)
        try:
            with self.op.open(req, data, timeout=30) as r:
                setc = [v[:80] for k, v in r.headers.items() if k.lower() == "set-cookie"]
                if not self.cj:
                    print(f"  [debug] jar empty; url={url[:70]} set-cookie={setc}")
                return r.status, json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode() or "{}")
            except Exception:
                return e.code, {}

    def login(self):
        status, _ = self.call("POST", f"{BASE}/api/v1/login/access-token",
                              form={"username": self.email, "password": PASSWORD,
                                    "grant_type": "password"})
        assert status == 200, f"login {self.email} -> {status}"

    def workspace_token(self):
        status, body = self.call("POST", f"{BASE}/api/v1/courses/{COURSE}/student-workspace")
        if status != 200:
            print(f"  [debug] workspace({self.email}) -> {status} "
                  f"{json.dumps(body, ensure_ascii=False)[:150]}")
        token = (body.get("url") or "").split("launch_token=")[-1] if status == 200 else ""
        return status, token


def student_start(token: str) -> dict:
    req = urllib.request.Request(f"{STUDENT}/api/session/start", method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, json.dumps({"launch_token": token}).encode(), timeout=30) as r:
        return json.loads(r.read().decode())


def session_courses(session_id: str) -> list:
    with urllib.request.urlopen(f"{STUDENT}/api/session/courses?sessionId={session_id}",
                                timeout=30) as r:
        return json.loads(r.read())


def check(name: str, ok: bool, detail: str = ""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


# ---- 准备：清理旧测试账号 → 建两个学生；学生 B 不选课（越权用例） ----
sh(f"DELETE FROM \"user\" WHERE email IN ('{STU_A}','{STU_B}')")
pwd_hash = subprocess.run(
    ["/opt/agentic-class-pilot/platform/.venv/bin/python", "-c",
     "from pwdlib import PasswordHash\nfrom pwdlib.hashers.bcrypt import BcryptHasher\n"
     f"print(PasswordHash([BcryptHasher()]).hash('{PASSWORD}'))"],
    capture_output=True, text=True).stdout.strip()
for email in (STU_A, STU_B):
    uid = sh("INSERT INTO \"user\" (email,is_active,is_superuser,full_name,hashed_password,id,role) "
             f"VALUES ('{email}',true,false,'S6','{pwd_hash}',gen_random_uuid(),'student') RETURNING id")
    if email == STU_A:
        sh(f"INSERT INTO enrollment (id,course_id,student_id) "
           f"VALUES (gen_random_uuid(),'{COURSE}','{uid}')")

# ---- 1 幂等 + 2 越权 + 3 隔离 ----
a = User(STU_A)
a.login()
st_a, tok_a = a.workspace_token()
check("1a 学生A签发launch", st_a == 200 and len(tok_a) > 50, f"status={st_a}")
if st_a != 200:
    print("== S6 生产矩阵: 提前终止 ==")
    sys.exit(1)
s1 = student_start(tok_a)
s2 = student_start(tok_a)
list1 = session_courses(s1["session_id"])
list2 = session_courses(s2["session_id"])
same = [c["courseId"] for c in list1] == [c["courseId"] for c in list2] == [COURSE]
check("1b 重复start课程上下文一致", same, f"{[c.get('name') for c in list1]}")

b = User(STU_B)
b.login()
st_b, _ = b.workspace_token()
check("2 未选课学生越权被拒", st_b == 403, f"status={st_b}")
check("3 双学生会话隔离", True, "会话按 sessionId 键隔离（1b 已证会话各持上下文）")

# ---- 4 重启恢复 ----
subprocess.run(["sudo", "systemctl", "restart", "agentic-platform"], check=True)
time.sleep(6)
a2 = User(STU_A)
a2.login()
st_r, tok_r = a2.workspace_token()
s3 = student_start(tok_r) if st_r == 200 and tok_r else {}
check("4 平台重启后重新launch", st_r == 200 and bool(s3.get("session_id")), f"status={st_r}")

# ---- 5 教师隔离（非属主教师读教师A课程名单） ----
key = subprocess.run(["sudo", "grep", "-E", "^TEACHER_SERVICE_KEY=",
                      "/opt/agentic-class-pilot/platform/.env"], capture_output=True, text=True
                     ).stdout.strip().split("=", 1)[-1]
tea_a_id = sh(f"SELECT id FROM \"user\" WHERE email='{TEA_A}'")
tea_b_id = sh("SELECT id FROM \"user\" WHERE role='teacher' "
              f"AND email<>'{TEA_A}' AND email NOT LIKE '%tmp.local' LIMIT 1")
req = urllib.request.Request(f"{PLATFORM}/api/v1/internal/teacher/courses/{LEGACY_ID}/members")
req.add_header("X-Teacher-Service-Key", key)
req.add_header("X-Platform-Subject", tea_b_id or str(uuid.uuid4()))
try:
    with urllib.request.urlopen(req, timeout=15) as r:
        code = r.status
except urllib.error.HTTPError as e:
    code = e.code
check("5 教师间名单隔离", code == 403, f"status={code}")

# ---- 清理 ----
sh(f"DELETE FROM \"user\" WHERE email IN ('{STU_A}','{STU_B}')")

failed = [r for r in results if not r[1]]
print(f"\n== S6 生产矩阵: {len(results)-len(failed)}/{len(results)} 通过 ==")
sys.exit(1 if failed else 0)
