# 模型工厂迁移计划（vendor 模板 → backend）

## 背景与目标

把 `vendor/fastapi-langgraph-agent-production-ready-template` 里的模型工厂（`app/services/llm/`：`LLMRegistry` 模型注册表 + `LLMService` 重试/循环降级服务）迁入我们后端，作为全系统统一的 LLM 调用入口；同时按用户决定**一并移除 Dify 集成**，让工厂成为唯一 LLM 路径。

用户已确认的两个取舍：
1. **registry 最小适配**：`service.py`、`__init__.py` 逐字复制；`registry.py` 只改 `_API_KEY` 一行 + `LLMS` 模型清单（gpt-5.x 清单在 DeepSeek 网关上不存在，必须换）。
2. **Dify 移除**：删 `services/dify.py`、config 的 `DIFY_*` 字段、`ask.py` 的 Dify 分支；相关测试改为 mock 模型工厂。

本任务是 `docs/langgraph-integration-plan.md` 中"config 驱动模型工厂"子项的落地，不引入 langgraph/agents/checkpoint（那是后续阶段）。

## 迁移对象与依赖分析（已核实）

工厂源码 3 个文件，内部耦合仅两处：`from app.core.config import settings`、`from app.core.logging import logger`。我们后端恰好也叫 `app` 包，且已有 `app.core.config`——所以**不需要动 import**，只需让我们的 `settings` 具备工厂读到的属性、补一个 `app/core/logging.py` 垫片。

`service.py`（不改）读的 settings 属性：`DEFAULT_LLM_MODEL`、`LLM_TOTAL_TIMEOUT`（运行时读）、`MAX_LLM_CALL_RETRIES`（**import 时**烘进 tenacity 装饰器）、`ENVIRONMENT.value`（须为枚举）。
`registry.py`（仅改清单）**import 时**执行 `_API_KEY = SecretStr(settings.OPENAI_API_KEY)` 并构造 `ChatOpenAI` 列表 → 属性缺省会 `SecretStr(None)` 直接炸 import，必须给字符串兜底。

## 改动计划表

| # | 文件 | 动作 |
|---|---|---|
| 1 | `backend/pyproject.toml` | 加直接依赖 `tenacity>=9,<10`、`openai>=2,<4`、`langchain-core>=1.0,<2`（`langchain-openai` 已在） |
| 2 | 根 `uv.lock` | `uv lock` 重锁 |
| 3 | `backend/app/core/config.py` | 加 `Environment` 枚举 + 工厂字段；删 `DIFY_API_KEY/DIFY_BASE_URL` |
| 4 | `backend/app/core/logging.py` | **新建**：structlog 风格 `logger` 垫片（不引入 structlog 依赖） |
| 5 | `backend/app/services/llm.py` | **删除**（被工厂取代；且与 `app/services/llm/` 包名冲突，必须让位） |
| 6 | `backend/app/services/llm/` | **新建包**：`__init__.py`、`service.py` 逐字复制；`registry.py` 复制后改 2 处 |
| 7 | `backend/app/services/dify.py` | **删除** |
| 8 | `backend/app/api/routes/ask.py` | 路由改 async，走 `llm_service.call`；删 Dify 分支 |
| 9 | 根 `.env` | `DIFY_API_KEY/DIFY_BASE_URL` 两行**直接删除**（用户确认不留底） |
| 10 | `backend/tests/api/routes/test_snapshot.py` | Dify 分支测试改为 mock `llm_service.call` |
| 11 | `backend/tests/services/test_llm_factory.py` | **新建**：registry + service 单测（fake 模型） |
| 12 | `backend/pyproject.toml`（mypy/ruff 段） | 视 lint 结果给 `app/services/llm/*` 加窄范围豁免，**不改源码** |

## 各项要点

### 3. config.py 字段（`LLM_*` 保持唯一配置源）

在 `LLM_MODEL` 之后追加（沿用文件里已有的 `model_validator` 惯例做单一来源推导）：

```python
class Environment(StrEnum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"

# --- LLM model factory (ported from vendor template) ---
ENVIRONMENT: Environment = Environment.DEVELOPMENT
DEFAULT_LLM_MODEL: str = ""   # 空 = 跟随 LLM_MODEL
MAX_TOKENS: int = 2000
MAX_LLM_CALL_RETRIES: int = 3
LLM_TOTAL_TIMEOUT: int = 60

@model_validator(mode="after")
def _default_llm_model(self) -> Self:
    if not self.DEFAULT_LLM_MODEL:
        self.DEFAULT_LLM_MODEL = self.LLM_MODEL
    return self
```

`.env` 无需新增任何条目（现有 `LLM_API_KEY/LLM_BASE_URL/LLM_MODEL` 即全部输入）。

### 4. logging 垫片（~30 行）

`service.py` 的调用形态：`logger.debug("event_name", key=value)`、`logger.warning(..., exc_info=True)`、`logger.exception(...)`，以及 tenacity 的 `before_sleep_log(logger, WARNING)` 会调 `logger.log(level, msg)`。垫片需提供 `debug/info/warning/error/exception/log` 六个方法，把 kwargs 格式化进消息、单独透传 `exc_info=True`，底层用 `logging.getLogger("app.llm")`。不复制 vendor 的 261 行 structlog 配置（那会连累我们的日志栈）。

### 6. registry.py 的两处改动

```python
_API_KEY = SecretStr(settings.LLM_API_KEY or "")   # 原: settings.OPENAI_API_KEY

LLMS: List[Dict[str, Any]] = [
    {
        "name": settings.LLM_MODEL,
        "llm": ChatOpenAI(
            model=settings.LLM_MODEL,
            api_key=_API_KEY,
            base_url=settings.LLM_BASE_URL,
            max_tokens=settings.MAX_TOKENS,
            temperature=0.3,   # 与原手写客户端行为对齐
        ),
    },
]
```

要点：用 `max_tokens` 而非 vendor 的 `max_completion_tokens`、去掉 `reasoning={"effort":...}`（两者都是 OpenAI 推理模型专属，DeepSeek 网关可能 400）；单条目 = 无跨模型降级但重试仍生效，以后往清单里加条目即获得降级链。文件其余部分（`get/get_all_names/get_model_at_index` 及注释）逐字保留。

### 8. ask.py 改造

- `def ask_chapter` → `async def ask_chapter`（`llm_service.call` 是协程；同步 SQLModel Session 在 async 路由里跑小查询，可接受的折衷，代码里加一行注释说明）。
- 删 `from app.services import dify, llm` 的 dify 部分 → `from app.services.llm import llm_service`；消息构造：

```python
from langchain_core.messages import HumanMessage, SystemMessage

try:
    answer_msg = await llm_service.call(
        [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user_prompt)]
    )
except RuntimeError as e:   # 全模型失败 / 总超时
    raise HTTPException(status_code=502, detail=str(e)) from e
answer = str(answer_msg.content)
```

- `services/__init__.py` 目前为空，无需 vendor 的 re-export。

### 11. 测试设计（沿用 `unittest.mock.patch` 惯例）

- registry：`get()` 默认返回共享实例且 `base_url == settings.LLM_BASE_URL`、`model_name == settings.LLM_MODEL`；未知名抛 `ValueError`；带 kwargs 返回全新实例。
- service：new 一个 `LLMService()`，把 `svc._llm` 换成 fake runnable（`ainvoke` 返回 `AIMessage("ok")`）验证成功路径；再用先抛 `openai.RateLimitError`（用 `httpx.Request/Response` 构造）后成功的 fake 验证重试计数。
- test_snapshot.py 原 Dify 测试（275-299 行）：`patch.object(llm_service, "call", AsyncMock(side_effect=capture))`，捕获 messages 断言 context 仍在 `HumanMessage.content` 里；删掉 `DIFY_API_KEY` 的 patch。
- 新测试目录是否需要 `__init__.py`：照 `tests/api/...` 现状镜像（实现时 Glob 确认）。

### 12. lint/mypy 豁免（保源码不变的代价）

vendored 代码用旧式 `List/Dict`、无类型 `**kwargs`，mypy strict + ruff UP 规则大概率报错。对策是在 `backend/pyproject.toml` 加窄范围配置（`[[tool.mypy.overrides]] module="app.services.llm.*" ignore_errors=true` + ruff per-file-ignores），以实际 lint 输出为准，宁可豁免不源码。

## 验证步骤

1. `uv lock && uv sync`（根目录 workspace）。
2. import 冒烟：`cd backend && uv run python -c "import app.main; from app.services.llm import llm_service; print(llm_service.get_llm())"`——验证 py3.14 下 langchain-openai 1.6.2 可用、settings 字段齐全、无 import 期炸裂。
3. `uv run bash scripts/lint.sh`（mypy+ruff），按需加豁免。
4. `uv run bash scripts/test.sh`（需 `app_test` Postgres @ localhost:5433 在跑）。存量用例 + 新增用例全绿。
5. 手工 e2e：`uv run fastapi dev` → 登录拿 token → `POST /api/v1/ask/chapters/{id}` 提问，应经工厂调 DeepSeek 返回中文回答，日志出现 `llm_service_initialized`。
6. 确认 Dify 已死：grep `dify` 无残留引用（除 git 历史）。

## 提交建议（当前分支 lzm）

工作区还有上一轮 vendor 引入留下的未提交改动（.gitignore/.dockerignore/pyproject/uv.lock/docs/langgraph-integration-plan.md/vendor pin）。建议先单独提交那批（"chore: vendor langgraph 模板"），本次工作分两个提交：
1. `feat(services): port LLM model factory from vendored template`（表 #1-#6、#12）
2. `refactor(ask): route chapter Q&A through model factory; drop Dify`（表 #7-#9、#11）

## 风险与备注

- **DeepSeek 参数兼容**：`max_tokens`/`temperature` 是最保守组合；若真机 5xx/400，第一怀疑对象是参数序列化，届时在 LLMS 条目上微调（仍属清单层改动）。
- **单例共享**：`llm_service` 是模块级单例，默认路径会在降级时改写 `self._llm`；当前单条目 + 不用 `bind_tools`，无碍。将来多 agent 接入时按 langgraph 计划文档的"每 agent 独立绑定"演进。
- **`ENVIRONMENT` 命名**：是 vendored `service.py` 的硬编码读取项，与现有 `FASTAPI_ENV` 并存（后者仅守卫默认密钥告警），互不干扰。
- **vendor 目录是嵌套 git 仓库**：本次只读取复制，不在其中做任何 git 操作。
- `findings.md/progress.md/task_plan.md` 是上轮会话遗留的未跟踪文件，不动。
