"""LLM 端点探针 —— 接真模型前先单独验证连通性。

为什么要单独有一个探针：
    teach 节点在 LLM 调用失败时会静默降级到确定性脚本，
    整节课照样能跑完。所以"跑通了"不等于"接上了"。
    探针直接暴露 HTTP 层结果，把这两件事分开。

用法：
    python orchestrator/llm_probe.py
    python orchestrator/llm_probe.py --verbose    # 打印模型原文返回

退出码：0 = 端点可用；1 = 未配置或调用失败。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "orchestrator"))

# 复用 agent 的 .env.local 加载逻辑，避免两处配置解析不一致
from agent import _load_dotenv  # noqa: E402

_load_dotenv()


def probe(verbose: bool = False) -> int:
    base = os.environ.get("AGENT_LLM_BASE_URL")
    key = os.environ.get("AGENT_LLM_API_KEY")
    model = os.environ.get("AGENT_LLM_MODEL")

    print("── LLM 端点配置 ──")
    print(f"  BASE_URL : {base or '(未设置)'}")
    print(f"  MODEL    : {model or '(未设置)'}")
    masked = f"{key[:6]}...{key[-4:]}" if key and len(key) > 12 else "(未设置)"
    print(f"  API_KEY  : {masked}")

    if not (base and key and model):
        print("\n✗ 三个变量未配齐 → teach 将走确定性降级脚本（不是接上大模型）")
        print("  复制 .env.local.example 为 .env.local 并填好 Key，或直接在命令行设置：")
        print('    export AGENT_LLM_BASE_URL=https://api.deepseek.com/v1')
        print('    export AGENT_LLM_API_KEY=sk-xxx')
        print('    export AGENT_LLM_MODEL=deepseek-chat')
        return 1

    if key.startswith("sk-在这里") or "在这里填" in key:
        print("\n✗ API_KEY 还是模板占位值，请填真实 Key")
        return 1

    print("\n── 发起真实请求 ──")
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": "你是一名课堂智能体。"},
                {"role": "user", "content": "用一句话说明什么是处理机调度。"},
            ],
            "max_tokens": 120,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:400]
        print(f"✗ HTTP {e.code} {e.reason}")
        print(f"  服务端返回：{body}")
        return 1
    except urllib.error.URLError as e:
        print(f"✗ 网络不可达：{e.reason}")
        print("  常见原因：代理未设置 / 域名被墙 / 公司网络拦截")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"✗ {type(e).__name__}: {e}")
        return 1

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        print("✗ 响应结构异常（没有 choices[0].message.content）")
        print(f"  原文：{json.dumps(data, ensure_ascii=False)[:400]}")
        return 1

    print("✓ 端点可用")
    print(f"\n── 模型回复 ──\n{content.strip()}")
    if verbose:
        usage = data.get("usage") or {}
        print(f"\n── usage ──\n  {usage}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="验证 AGENT_LLM_* 端点是否可用")
    ap.add_argument("--verbose", action="store_true", help="打印 usage 等附加信息")
    args = ap.parse_args()
    raise SystemExit(probe(args.verbose))
