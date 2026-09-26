"""Per-turn LLM override (platform BYOK personal model config).

会话层（apps/server.py）在每轮 `run_turn_stateless` 前把当前用户的平台
模型配置放进 threading.local，`agent.llm_chat` / `agent.llm_available`
经 `llm_params()` 读取：**BYOK 优先，环境变量兜底**。

为什么用 threading.local：`graph.invoke` 在单个工作线程内同步跑完，
心跳线程是独立线程，各自持有各自的 override —— 并发会话互不串扰；
轮次结束后会话层显式清除。
"""
import os
import threading

_local = threading.local()


def set_llm_override(cfg: dict | None) -> None:
    """设置本轮生效的 BYOK 配置（形如 {"llm": {...}}}）；None 清除。"""
    _local.llm_cfg = cfg


def get_llm_override() -> dict | None:
    return getattr(_local, "llm_cfg", None)


def llm_params() -> tuple[str, str, str]:
    """返回 (base_url, api_key, model)。BYOK 三项齐全时优先，否则读环境变量。"""
    cfg = getattr(_local, "llm_cfg", None) or {}
    llm = cfg.get("llm") or {}
    base = str(llm.get("baseUrl") or "").strip()
    key = str(llm.get("apiKey") or "").strip()
    model = str(llm.get("model") or "").strip()
    if base and key and model:
        return base, key, model
    return (
        os.environ.get("AGENT_LLM_BASE_URL", "").strip(),
        os.environ.get("AGENT_LLM_API_KEY", "").strip(),
        os.environ.get("AGENT_LLM_MODEL", "").strip(),
    )
