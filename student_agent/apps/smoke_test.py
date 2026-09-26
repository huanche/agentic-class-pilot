"""课前彩排：不改任何教学代码，只驱动 HTTP 会话接口。

四种用法（前提：服务已启动 `python apps/start.py`）：

    python apps/smoke_test.py auto --scale 30   # 全程不发言，看时钟能不能把课上完
    python apps/smoke_test.py stages            # ★ 老师的三个按钮走一遍完整流程
    python apps/smoke_test.py chat              # 模拟学生答题，看反馈与判星
    python apps/smoke_test.py export --session X

`stages` 是这次最该跑的一次检查：开始上课 → 视频播完 → 复述 → 下一环节 →
深度探究 → 下课，全靠外部按钮驱动，不需要等真实时间流逝。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

HOST = "http://127.0.0.1:8000"

# 本地服务不走系统代理：挂着 HTTP_PROXY 的机器上 urllib 会被代理拦下报 422
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(path: str, payload: dict | None = None, method: str | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(
        HOST + path, data=data, method=method or ("POST" if data else "GET"),
        headers={"Content-Type": "application/json"} if data else {},
    )
    with OPENER.open(r, timeout=300) as resp:
        return json.load(resp)


def fetch(path: str) -> str:
    with OPENER.open(HOST + path, timeout=60) as r:
        return r.read().decode("utf-8")


def show(messages: list[dict]) -> None:
    for m in messages:
        src = "AI " if m.get("llm") else "模板"
        print(f"  [{src}] {m['text'].replace(chr(10), ' ')[:96]}")


def open_session(sid: str, scale: float = 1.0) -> dict:
    """进教室。**不自动上课** —— 起课铃是单独的一步。"""
    st = call("/api/session/start", {"session_id": sid, "time_scale": scale})
    assert st["status"] == "idle", f"刚建好应该处于待机，实际 {st['status']}"
    return st


def ring_bell(sid: str) -> dict:
    out = call(f"/api/session/{sid}/begin", method="POST")
    print(f"\n=== 起课铃 ===\n  {out['reply_text'][:200]}")
    return out


def drain(sid: str, cursor: int) -> int:
    ms = call(f"/api/session/{sid}/messages?since={cursor}")
    show(ms["messages"])
    return int(ms["total"])


def cmd_auto(sid: str, scale: float, tick: float) -> int:
    """自动驾驶：只有上课那一刻按一下铃，之后全靠心跳推。"""
    open_session(sid, scale)
    print(f"会话 {sid}，time_scale={scale}（一节课约 {45 / scale * 60:.0f} 秒）")
    ring_bell(sid)
    base = f"/api/session/{sid}"
    cursor, trace = 0, []
    for _ in range(240):
        st = call(base + "/state")
        cursor = drain(sid, cursor)
        if not trace or trace[-1] != st["phase"]:
            trace.append(st["phase"])
            print(f"---- ▸ {st['phase_name']} ----")
        if st["status"] == "ended":
            print("\n下课。阶段轨迹：" + " → ".join(trace))
            return 0
        time.sleep(tick)
    print("\n超时未下课，阶段轨迹：" + " → ".join(trace))
    return 1


ANSWERS = [
    "CPU 一次只能跑一个进程，所以要靠调度规则决定谁先用、用多久。",
    "高级调度把作业从外存调入内存变成进程，低级调度从就绪队列挑一个上 CPU，"
    "中级调度负责把暂时不跑的进程换出去。",
    "周转时间是从作业提交到完成，带权周转时间是周转时间除以运行时间，"
    "响应时间是第一次拿到 CPU 的时间。",
    "非剥夺式只有进程主动放弃 CPU 才切换，剥夺式可以按优先级或时间片把正在跑的进程打断。",
]


def cmd_stages(sid: str) -> int:
    """★ 用老师的三个按钮走完一节课（不等真实时间）。"""
    open_session(sid, 1.0)
    ring_bell(sid)
    base = f"/api/session/{sid}"
    cursor = 0
    answered = 0
    answered_in: dict[str, bool] = {}      # 每个提问环节答一题就走，模拟老师控节奏

    for round_no in range(30):
        st = call(base + "/state")
        cursor = drain(sid, cursor)
        phase = st["phase"]
        print(f"\n---- 第{round_no + 1}步 · {st['phase_name']} "
              f"（素材 {st['segment_cursor']}/{st['segment_total']}）----")

        if st["status"] == "ended":
            print("\n下课了，全部环节走完。")
            return 0

        if phase == "guided_learning":
            if st["segment_cursor"] >= st["segment_total"]:
                out = call(f"{base}/stage/next", method="POST")
                print("  ▸ 下一环节：" + out["reply_text"][:120])
            else:
                out = call(f"{base}/media/done", None, method="POST")
                reason = out.get("advance_reason") or ""
                print(f"  ▸ 视频播完（{reason or '继续讲下一段'}）："
                      f"{out['reply_text'][:120]}")
        else:
            # 复述 / 深度探究：答一题，下一步就让老师跳下一环节
            if st.get("current_question") and not answered_in.get(phase):
                answered_in[phase] = True
                ans = ANSWERS[answered % len(ANSWERS)]
                answered += 1
                out = call(f"{base}/message", {"text": ans})
                print(f"  学生> {ans[:40]}…")
                print(f"  老师> {out['reply_text'][:120]}")
            else:
                out = call(f"{base}/stage/next", method="POST")
                print("  ▸ 下一环节：" + out["reply_text"][:120])

    print("\n[!] 30 步还没下课，检查一下剩下的 remaining_stages")
    return 1


def cmd_chat(sid: str) -> int:
    open_session(sid, 1.0)
    ring_bell(sid)
    base = f"/api/session/{sid}"
    # 真实流程：讲解 = 整段视频，播完上报后才进入复述问答
    call(f"{base}/media/done", None, method="POST")
    for a in ANSWERS[:3]:
        print(f"\n学生> {a}")
        out = call(f"{base}/message", {"text": a})
        print(f"老师> {out['reply_text'][:180]}")
        st = call(base + "/state")
        print("星级>", "  ".join(f"{k}={'★' * v or '—'}"
                                 for k, v in sorted(st["stars"].items())))
    return 0


def cmd_export(sid: str) -> int:
    print(fetch(f"/api/session/{sid}/export?fmt=md"))
    return 0


def main() -> int:
    global HOST
    p = argparse.ArgumentParser(description="课前彩排")
    p.add_argument("mode", choices=["auto", "stages", "chat", "export"])
    p.add_argument("--host", default=HOST)
    p.add_argument("--session", default=None)
    p.add_argument("--scale", type=float, default=30.0,
                   help="auto 模式的时间倍速，30 = 45 分钟压缩到约 90 秒")
    p.add_argument("--poll", type=float, default=3.0, help="auto 模式的轮询间隔（秒）")
    a = p.parse_args()

    HOST = a.host.rstrip("/")
    sid = a.session or f"{a.mode}-{int(time.time()) % 100000}"

    try:
        if a.mode == "auto":
            return cmd_auto(sid, a.scale, a.poll)
        if a.mode == "stages":
            return cmd_stages(sid)
        if a.mode == "chat":
            return cmd_chat(sid)
        return cmd_export(sid)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        print(f"接口报错 {e.code}：{detail}", file=sys.stderr)
        return 2
    except urllib.error.URLError as e:
        print(f"连不上服务：{e}\n先启动：python apps/start.py", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
