"""命令行上课窗口。

给不想等前端的人用：直接在这里把一节课走完，每个动作都对应一个 HTTP 接口，
和前端同学调的是同一批接口，所以这里能跑通，他那边接上去就能跑通。

    python apps/cli.py                      # 交互窗口
    python apps/cli.py --sid demo-1         # 指定会话号
    python apps/cli.py --scale 12           # 12 倍速压缩课时，演练用

直接打字 = 学生发言；以 / 开头 = 命令（/help 看全部）。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPORT_DIR = ROOT / "runtime" / "exports"

HELP = """\
命令                作用                                    对应接口
/begin             ★ 课堂开始（起课铃）                    POST /api/session/<sid>/begin
/video             ★ 报告：讲解视频全部播完了（一次）       POST /api/session/<sid>/media/done
/next              ★ 下一环节（老师掌控节奏，无条件切幕）   POST /api/session/<sid>/stage/next
/state             当前阶段、计时、进度、可用动作           GET  /api/session/<sid>/state
/stars             知识点星级                               stars / export
/msgs              重看全部对话                             GET  /api/session/<sid>/messages
/export [md|json]  导出学情到 runtime/exports/              GET  /api/session/<sid>/export
/new [会话号]      换一节新课（新学生）
/stop              停课（下课）
/help              这份说明
/quit              退出（服务继续在后台跑）

不打 / 就直接说话 = 学生发言 → POST /api/session/<sid>/message
"""

STATUS_TEXT = {
    "idle": "等待上课",
    "running": "上课中",
    "ended": "已下课",
}


class ApiError(Exception):
    pass


class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        # 本地服务不走系统代理：挂着 HTTP_PROXY 的机器上 urllib 会被代理拦下报 422
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(self, method: str, path: str, body: dict | None = None,
             raw: bool = False) -> dict | str:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with self.opener.open(req, timeout=60) as r:
                text = r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise ApiError(f"HTTP {e.code} {detail}") from None
        except OSError as e:
            raise ApiError(f"连不上服务（{self.base}）：{e}") from None
        if raw:
            return text
        return json.loads(text) if text.strip() else {}


def _print_reply(d: dict) -> None:
    text = (d.get("reply_text") or "").strip()
    if not text:
        return
    label = d.get("phase_name") or d.get("phase") or ""
    print()
    for line in text.splitlines():
        print(f"  {line}" if line else "")
    if label:
        print(f"         —— [{label}]")
    print()


def _print_state(d: dict) -> None:
    print()
    print(f"  状态        {STATUS_TEXT.get(d.get('status'), d.get('status'))}"
          f"（{d.get('status')}）")
    print(f"  当前环节    {d.get('phase_name')}（{d.get('phase')}）"
          f"  下一个：{d.get('next_stage') or '——（下一幕即下课）'}")
    print(f"  本幕计时    {d.get('stage_elapsed_minutes')} / "
          f"{d.get('stage_budget_minutes')} 分钟")
    print(f"  全课计时    {d.get('lesson_elapsed_minutes')} / "
          f"{d.get('total_minutes')} 分钟")
    print(f"  素材进度    第 {d.get('segment_cursor')} 段 / 共 {d.get('segment_total')} 段"
          f"   已播完 {len(d.get('played_media') or [])} 段")
    if d.get("current_question"):
        print(f"  当前提问    {d['current_question']}")
    stars = d.get("stars") or {}
    if stars:
        s = " ".join(f"{kp}:{'★' * v or '—'}" for kp, v in sorted(stars.items()))
        print(f"  掌握星级    {s}")
    acts = "、".join(d.get("available_actions") or [])
    print(f"  可做的动作  {acts or '——'}")
    print()


def _print_stars(d: dict) -> None:
    stars = d.get("stars") or {}
    if not stars:
        print("\n  还没有记录（星级在复述、探究环节才会记）\n")
        return
    print()
    for kp, v in sorted(stars.items()):
        print(f"  {kp}  {'★' * v or '—':<10} {v} 星")
    print()


class Runner:
    def __init__(self, api: Api, sid: str, scale: float, student_id: str) -> None:
        self.api = api
        self.sid = sid
        self.student_id = student_id
        self.open_session(scale)

    def open_session(self, scale: float) -> None:
        self.api.call("POST", "/api/session/start", {
            "session_id": self.sid, "time_scale": scale, "student_id": self.student_id,
        })

    def state(self) -> dict:
        d = self.api.call("GET", f"/api/session/{self.sid}/state")
        assert isinstance(d, dict)
        return d

    def say(self, text: str) -> None:
        d = self.api.call("POST", f"/api/session/{self.sid}/message", {"text": text})
        assert isinstance(d, dict)
        _print_reply(d)

    def begin(self) -> None:
        _print_reply(self.api.call("POST", f"/api/session/{self.sid}/begin"))  # type: ignore[arg-type]

    def video(self, seg: str | None) -> None:
        body = {"segment_id": seg} if seg else None
        d = self.api.call("POST", f"/api/session/{self.sid}/media/done", body)
        assert isinstance(d, dict)
        _print_reply(d)
        if d.get("advance_reason"):
            print(f"        （{d['advance_reason']}）")
        print()

    def next_stage(self) -> None:
        _print_reply(self.api.call("POST", f"/api/session/{self.sid}/stage/next"))  # type: ignore[arg-type]

    def msgs(self) -> None:
        d = self.api.call("GET", f"/api/session/{self.sid}/messages")
        assert isinstance(d, dict)
        for m in d.get("messages", []):
            who = "学生" if m["role"] == "student" else "AI"
            tag = m.get("phase") or ""
            print(f"  [{m['seq']}] {who}{'·' + tag if tag else ''}：{m['text']}")
        print()

    def export(self, fmt: str) -> None:
        txt = self.api.call("GET", f"/api/session/{self.sid}/export?fmt={fmt}", raw=True)
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        p = EXPORT_DIR / f"{self.sid}.{fmt}"
        p.write_text(str(txt), encoding="utf-8")
        print(f"\n  已导出：{p}\n")

    def stop(self) -> None:
        self.api.call("DELETE", f"/api/session/{self.sid}")
        print("\n  已停课\n")


def main() -> int:
    p = argparse.ArgumentParser(description="命令行上课窗口")
    p.add_argument("--host", default="http://127.0.0.1:8000")
    p.add_argument("--sid", default="")
    p.add_argument("--student", default="student-001")
    p.add_argument("--scale", type=float, default=1.0,
                   help=">1 压缩课时，例如 12 = 45 分钟压成约 4 分钟")
    a = p.parse_args()

    import uuid
    sid = a.sid or f"cli-{uuid.uuid4().hex[:6]}"
    api = Api(a.host)
    try:
        r = Runner(api, sid, a.scale, a.student)
    except ApiError as e:
        print(f"[x] {e}")
        print("    先在另一个窗口：python apps/start.py")
        return 1

    print()
    print("=" * 62)
    print("  命令行上课窗口")
    print(f"  会话 {sid}   服务 {a.host}" + (f"   {a.scale} 倍速" if a.scale > 1 else ""))
    print("  输入 /help 看命令，直接打字就是学生发言")
    print("=" * 62)
    print(HELP)

    while True:
        try:
            st = r.state()
            tag = f"{STATUS_TEXT.get(st.get('status'), '?')}·{st.get('phase_name') or '—'}"
        except ApiError:
            tag = "离线"
        try:
            line = input(f"[{tag}] > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  退出（课还在后台上着，重新跑本脚本可继续）")
            return 0

        if not line:
            continue
        try:
            if not line.startswith("/"):
                r.say(line)
                continue
            cmd, *rest = line.split(maxsplit=1)
            arg = rest[0].strip() if rest else ""
            c = cmd.lower()
            if c in ("/quit", "/exit", "/q"):
                print("  退出（课还在后台跑）")
                return 0
            if c == "/help":
                print(HELP)
            elif c == "/begin":
                r.begin()
            elif c == "/video":
                r.video(arg or None)
            elif c == "/next":
                r.next_stage()
            elif c == "/state":
                _print_state(r.state())
            elif c == "/stars":
                _print_stars(r.state())
            elif c == "/msgs":
                r.msgs()
            elif c == "/export":
                r.export(arg or "md")
            elif c == "/stop":
                r.stop()
            elif c == "/new":
                sid = arg or f"cli-{uuid.uuid4().hex[:6]}"
                r = Runner(api, sid, a.scale, a.student)
                print(f"\n  新课：{sid}\n")
            else:
                print(f"  未知命令：{cmd}（/help 看全部）")
        except ApiError as e:
            print(f"  [x] {e}")
        except KeyboardInterrupt:
            print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
