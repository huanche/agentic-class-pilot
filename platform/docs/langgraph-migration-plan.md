# LangGraph 模板迁移详解（逐文件版）

> **2026-09-16 源码核对补充**：完整函数级调用链、迁移规模、当前实现缺口与修订后的实施顺序，见 [LangGraph 迁移范围与底层函数清单](langgraph-migration-inventory.md)。当前工作区已存在第 2 步代码，但不据此认定已完成运行验收；下文保留原阶段方案与历史进度记录。

> 源：`vendor/fastapi-langgraph-agent-production-ready-template`（下文简称"模板"，所有模板路径省略此前缀）
> 目标：`backend/`。我们已迁移其 LLM 模型工厂（`backend/app/services/llm/`，适配 DeepSeek），本文覆盖其余全部能力的逐文件迁移说明。
> 每个文件按三段写：**它是干嘛的**（内部机制）→ **迁移改造**（落点 + 需要改什么）→ **依赖**。
>
> **进度**：✅ 第 1 步已完成（2026-09-16）——`app/schemas/`、`app/core/langgraph/utils.py`、`app/core/prompts/` 落地，新增依赖 `langgraph`+`tiktoken`，配置项 `LLM_CONTEXT_TOKENS`，23 个单元测试通过。
> ✅ 第 2 步已完成（2026-09-16）——`app/core/langgraph/tools/`（空注册表）+ `graph.py`（LangGraphAgent，含 `close()` 支持重复 lifespan）落地，`main.py` lifespan fail-fast 预热，配置项 `CHECKPOINT_TABLES`/`CHECKPOINT_POOL_SIZE`，新增依赖 `langgraph-checkpoint-postgres`；单测 11 个新增（全套 133 通过），附 E 验收脚本 `scripts/verify_langgraph_agent.py` 全项通过（多轮累积/线程隔离/三表落库/清空）。适配细节见 graph.py 模块头。**坑（已解）**：psycopg 异步不支持 Windows ProactorEventLoop（测试用 conftest 设 Selector policy；裸跑 uvicorn 需 `--reload`）；`CREATE INDEX CONCURRENTLY` 会等所有旧事务——测试 conftest 预建 checkpoint schema 再开 db 长事务，否则 lifespan 预热挂死。
> ✅ 第 3 步已完成（2026-09-16）——`app/api/routes/chat.py`（会话 CRUD + chat/SSE/历史/清空 8 端点，路径 `/api/v1/chat/sessions/...`）+ `ChatSession` 表（alembic `a7e3f92c1d64`，thread_id=str(id)，chapter_id 可空 FK）+ `app/services/chat_sessions.py`（所有权 404 语义）落地；ask.py 抽出 `latest_courseware_context()` 供章节会话注入课件上下文（旧路由行为不变）；schemas 增 `HistoryMessage` 解除输出 3000 长度上限（inventory 缺口 #1）。**适配决策**：只转发最新一条 user 消息（防全量重串重复累积）；SSE 错误帧用通用文案不泄内部详情；他人会话一律 404。单测 14 个新增（全套 147 通过）；真机验收（qwen-max）：SSE 帧 + done:true、多轮记忆、GET/DELETE messages、删会话 404 全过。
> ✅ 前端已接学生端章节问答（同日）——AskPanel 改走新端点（非流式）：每 (user, chapter) 一个会话（`GET /chat/sessions?chapter_id=` find-or-create），历史从 checkpoint 恢复、跨访问持久；发消息后以服务端全量历史为准。SSE 消费暂缓；旧 /ask 路由保留未删。
> 🎯 **范围决策（2026-09-16）**：第 4 步整体不做——不引入 mem0/pgvector/向量数据库（短期记忆 + checkpoint 已满足当前产品形态）；会话自动命名随之取消（章节会话标题即章节名）；缓存层失去主要消费方，一并取消。第 5/6 步（限流/指标/结构化日志/Langfuse/评估）降级为"对外部署前再评估"。剩余可选项：SSE 前端消费、旧 /ask 路由下线、checkpoint 历史清理、教学工具（按需）。
> ✅ 前端 SSE 已接（同日，即上面可选项的第一项）——新增 `frontend/src/lib/streamChat.ts`（原生 fetch + ReadableStream 逐帧解析，浏览器端 axios/XHR 无法流式读 body 故绕开生成客户端）；AskPanel 发送路径默认改流式：乐观双气泡（user 问题 + 空 assistant 泡），token 帧逐块追加（打字机），`done=true` 收尾后 invalidate 消息查询回源 checkpoint；错误帧（done+文案）→ 回滚 + toast；组件卸载 abort。build/biome 全绿；Node 复刻同解析路径对真后端验证通过（分块 3 帧 + done 收尾）。

---

## 0. 全景导览

### 0.1 模板一次聊天请求的完整生命周期

先看懂这张图，后面每个文件都能对号入座：

```
POST /chat/stream（chatbot.py L77）
  │  get_current_session 校验 per-session JWT
  │  maybe_name_session → 首条消息时原子认领 + 后台 LLM 起标题（session_naming.py）
  ▼
LangGraphAgent.get_stream_response（graph.py L339）
  │  ① asyncio.gather 并发：读 checkpoint 状态（aget_state）+ mem0 记忆检索（memory.py）
  │  ② 若图停在上次 interrupt → Command(resume=用户输入) 恢复（HITL）
  │     否则 → 新输入 {messages, long_term_memory}
  ▼
graph.astream(stream_mode="messages")   ← 逐 token 吐给 SSE
  │
  ├─ chat 节点（graph.py L130）
  │    load_system_prompt（prompts/__init__.py：用户名+时间+长期记忆注入 system.md 模板）
  │    → prepare_messages（utils/graph.py：tiktoken 计数 + trim_messages 裁剪上下文）
  │    → llm_service.call（已迁移的模型工厂：重试+循环 fallback，工具绑定保持）
  │    → 有 tool_calls？→ goto "tool_call" / 无 → END（用 Command 路由）
  │
  ├─ tool_call 节点（graph.py L187，RetryPolicy(3)）
  │    多工具 asyncio.gather 并发执行 → ToolMessage 回填 → goto "chat"（循环）
  │    工具内部可调 interrupt() 暂停整图 → 存入 checkpoint 等人类回复
  │
  ▼
  全程状态自动持久化到 AsyncPostgresSaver（Postgres 三张 checkpoint 表）
  流结束后 fire-and-forget：asyncio.create_task(memory.add(...)) 写长期记忆
```

贯穿全程的横切面（模板在生产加固上的功夫）：Prometheus 计时埋点、structlog 上下文日志、correlation-id、限流装饰器、Langfuse trace 回调——这些在图/路由代码里以一行引用的形式存在，可按阶段先裁剪后接回。

### 0.2 目录对照总表（模板文件 → 我们的落点）

| 模板文件                                                               | 我们的落点                                                                      | 迁移批次 |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------------------- | -------- |
| `app/schemas/graph.py`                                               | `backend/app/schemas/graph.py`（新建 schemas 包）                             | 第 1 步  |
| `app/schemas/chat.py`                                                | `backend/app/schemas/chat.py`                                                 | 第 1 步  |
| `app/utils/graph.py`                                                 | `backend/app/core/langgraph/utils.py`                                         | 第 1 步  |
| `app/core/prompts/*`（3 文件）                                       | `backend/app/core/prompts/*`                                                  | 第 1 步  |
| `app/core/langgraph/tools/*`                                         | `backend/app/core/langgraph/tools/*`                                          | 第 2 步  |
| `app/core/langgraph/graph.py`                                        | `backend/app/core/langgraph/graph.py`                                         | 第 2 步  |
| （checkpoint 表）                                                      | 同一 Postgres，`checkpointer.setup()` 自建                                    | 第 2 步  |
| `app/api/v1/chatbot.py`                                              | `backend/app/api/routes/chat.py` + 新增 ChatSession 表                        | 第 3 步  |
| `app/services/memory.py`                                             | `backend/app/services/memory.py`                                              | 第 4 步  |
| `app/services/session_naming.py`                                     | `backend/app/services/session_naming.py`                                      | 第 4 步  |
| `app/core/cache.py`                                                  | `backend/app/core/cache.py`                                                   | 第 5 步  |
| `app/core/limiter.py`                                                | `backend/app/core/limiter.py`                                                 | 第 5 步  |
| `app/core/metrics.py` + `prometheus/` + `grafana/`               | `backend/app/core/metrics.py` + 仓库根监控配置                                | 第 5 步  |
| `app/core/logging.py`                                                | 替换`backend/app/core/logging.py`（现为 shim）                                | 第 5 步  |
| `app/core/middleware.py`                                             | `backend/app/core/middleware.py`                                              | 第 5 步  |
| `app/core/observability.py`                                          | `backend/app/core/observability.py`                                           | 第 6 步  |
| `evals/*`                                                            | `backend/evals/*`                                                             | 第 6 步  |
| `app/core/config.py`                                                 | 不搬整体，只把新增配置项并入`backend/app/core/config.py`（pydantic-settings） | 各步随迁 |
| `app/api/v1/auth.py`、`app/services/database.py`、`app/models/*` | **不迁移**（我们已有 per-user JWT 体系；模板此处是反面教材）              | —       |

---

## 第 1 步：图骨架（schema + 消息工具 + 提示词）

### 1.1 `app/schemas/graph.py`（19 行）— 图状态定义

**它是干嘛的**：定义 LangGraph 图的共享状态 `GraphState`（graph.py L12 引用）。两个关键点：

- `messages: Annotated[list, add_messages]`（L15）——`add_messages` 是 LangGraph 的 **reducer**：每个节点返回的消息不是覆盖旧值，而是按消息 `id` 智能合并追加。这就是"多轮对话历史自动累积"的机制，对话历史存在状态里而非靠路由层拼接。
- `long_term_memory: str`（L18）——每次调用时把 mem0 检索到的长期记忆作为字符串塞进状态，`_chat` 节点读它注入 system prompt。

**迁移改造**：落到 `backend/app/schemas/graph.py`。我们后端目前没有 `schemas/` 包（Pydantic 模型都挤在 `models.py` 里），建议新建该包承接 API 请求/响应与图状态，和 SQLModel ORM 分离。文件本身零改动照搬。

**依赖**：`langgraph`（`add_messages` 来自 `langgraph.graph.message`）。

### 1.2 `app/schemas/chat.py`（107 行）— 聊天请求/响应模型

**它是干嘛的**：五个模型，chatbot.py 全部引用：

- `Message`（L18）——role（user/assistant/system 三值）+ content；L31 的 `validate_content` 校验器拒绝 `<script>` 标签和空字节（输入卫生的第一道闸）；content 限长 1~3000。
- `ChatRequest`（L56）——`messages` 列表至少 1 条。
- `ChatResponse` / `StreamResponse`（L70/L80）——后者是 SSE 帧结构：`{content: 当前片段, done: 是否结束}`，前端靠 `done=true` 收尾。
- `SessionTitle`（L92）——给会话起名用的**结构化输出 schema**（配合第 4 步 session_naming 的 `response_format`），L101 校验器把标题规范化（去多余空白和首尾标点）。

**迁移改造**：落到 `backend/app/schemas/chat.py`。模板的 `BaseResponse`（带 success 字段的包装）我们没有——直接去掉这个基类，让 `ChatResponse`/`StreamResponse` 继承 `BaseModel` 即可。另外我们已有 `ChapterAskRequest/Response` 在 models.py，本步不动它，第 3 步接路由时再决定去留。

**依赖**：无新增。

### 1.3 `app/utils/graph.py`（139 行）— 消息处理五件套

**它是干嘛的**：图节点的所有"消息杂活"，graph.py 高频引用：

- `_TIKTOKEN_ENCODING`（L12-15）——模块级缓存 tiktoken 编码器。先 `encoding_for_model(DEFAULT_LLM_MODEL)`，`KeyError` 时兜底 `cl100k_base`。**这个兜底对我们恰好必要**：DeepSeek 不是 tiktoken 已知模型，必走 fallback，计数是近似值但对裁剪够用。
- `_count_tokens_tiktoken`（L18）——本地计数不发 API：每条消息 +4 开销（角色头），对 str/dict/BaseMessage 三种形态分别累计，结尾 +2（assistant 起始）。
- `dump_messages`（L42）——Pydantic Message → dict 列表（喂给 llm_service.call）。
- `extract_text_content`（L54）——从 LLM content 里提取纯文本。content 可能是 str 或**结构化块列表**（GPT-5 Responses API 返回 `[{"type":"reasoning"...},{"type":"text"...}]`），text 块取文、reasoning 块跳过。流式路径每个 token 都走它。
- `process_llm_response`（L86）——非流式路径的对应物：把 list 型 content 归一化成 str。
- `prepare_messages`（L105）——**上下文裁剪**：`trim_messages(strategy="last", max_tokens=MAX_TOKENS, start_on="human", include_system=False, allow_partial=False)` 只保最近的 token 预算内消息；L125 捕获 `ValueError`——遇到不认识的 content 块（如 reasoning 块）就**放弃裁剪返回全部**，宁可多花 token 不崩。最后前置 system prompt。

**迁移改造**：我们后端只有单文件 `backend/app/utils.py`，没有 `utils/` 包——不要为它改包结构，这些函数本来就是图专用的，落到 `backend/app/core/langgraph/utils.py`。引用处从 `app.utils` 改为相对导入。`MAX_TOKENS` 改读我们 config 的对应字段（建议加 `LLM_CONTEXT_TOKENS`，与生成侧 max_tokens 区分）。

**依赖**：`tiktoken`——**注意模板自己都没在 pyproject 声明它，属隐性坑，我们必须显式添加**。

### 1.4 `app/core/prompts/`（3 文件，~55 行）— 提示词模板体系

**它是干嘛的**：

- `__init__.py`——**模块加载时一次性读入** `system.md` / `session_title.md` 缓存为字符串（L11 注释：no file I/O per request）；`load_system_prompt(username, **kwargs)`（L19）用 `str.format` 注入四个变量：`agent_name`、`current_date_and_time`（每次调用取当前时间——让模型知道"现在"）、`user_context`（有用户名时注入"你在和 {username} 对话"）、`long_term_memory`（透传 mem0 检索结果）。
- `system.md`——通用助手模板，带 `{agent_name}` `{user_context}` `{long_term_memory}` `{current_date_and_time}` 占位符。
- `session_title.md`——起标题指令（第 4 步用）。

**迁移改造**：结构照搬到 `backend/app/core/prompts/`，但 **system.md 内容重写**：把我们 `ask.py` L25 的中文助教 SYSTEM_PROMPT 扩写成模板，新增占位符 `{chapter_context}`（章节标题/说明/课件文本，来自 `ask.py` 的 `_classroom_context`），这样章节问答的上下文也走统一的模板注入管道。这是"旧 ask 能力"和"新 agent 框架"的融合点。

**依赖**：无新增。

---

## 第 2 步：智能体核心（工具 + 图 + 检查点）

### 2.1 `app/core/langgraph/tools/`（3 文件，~50 行）— 工具注册表

**它是干嘛的**：

- `__init__.py` L13——`tools: list[BaseTool]` 就是全部注册机制：加工具 = 往列表里放。graph.py L77 `bind_tools(tools)` 绑给 LLM，L78 建 `tools_by_name` 字典供节点分发。
- `ask_human.py` L12——**HITL（人机协同）原语**：`@tool ask_human(question)` 内部调 `langgraph.types.interrupt(question)`。工具被调用时整图**暂停**，question 存进 checkpoint，接口层返回给人类；人类答复后由 `Command(resume=答复)` 从断点恢复，`interrupt()` 的返回值就是人类输入。用于删除数据、发邮件等不可逆操作前的确认。
- `duckduckgo_search.py`——langchain-community 的 `DuckDuckGoSearchResults(num_results=10, handle_tool_error=True)` 包装。

**迁移改造**：建 `backend/app/core/langgraph/tools/`。**两个 demo 工具都不搬**（公网搜索非教学场景；ask_human 等有真实确认需求时再加）。第一步建空注册表 `tools: list[BaseTool] = []` 先跑通无工具模式；将来教学场景工具（如"检索本课程大纲""查本章节课件原文"）往里加即可，图的代码零改动——这正是这个注册表设计的价值。

**依赖**：无新增（空注册表阶段）。

### 2.2 `app/core/langgraph/graph.py`（474 行）— LangGraphAgent，主菜

整个模板的灵魂，逐段拆解：

**`__init__`（L73）**：`llm_service.bind_tools(tools)`（工具绑定随 fallback 换模型时保持——这是我们已迁移的 service.py 已有的能力）+ 建 `tools_by_name` 索引 + 惰性 `_graph`/`_connection_pool`。

**`_get_connection_pool`（L87）**：为 checkpointer 建**独立的** psycopg `AsyncConnectionPool`（不复用业务 DB 连接）。参数有讲究：`autocommit=True`（checkpointer 自管事务）、`prepare_threshold=None`（**禁用 prepared statements**——langgraph checkpointer 与 psycopg 预编译语句不兼容，漏配会炸）、`connect_timeout=5`、`row_factory=dict_row`。L120-127 是设计亮点：**建池失败直接 raise，绝不静默降级**——注释原话：checkpointer 是会话历史和 HITL 恢复状态的唯一存储，没有它继续服务等于丢数据，不如暴露故障。

> **设计决策（本站）**：fail-fast 而非降级。我们迁移时保留这个语义——连接池起不来就让启动失败，不做"无记忆模式"兜底。

**`_chat` 节点（L130）**：一次 LLM 调用的完整封装：`load_system_prompt`（注入用户名+长期记忆）→ `prepare_messages`（裁剪）→ `llm_service.call`（外面包着 Prometheus 计时 L157）→ `process_llm_response` 归一化 → **用 `Command(update={messages: [回复]}, goto=...)` 路由**（L176）：回复带 `tool_calls` 就 goto `"tool_call"`，否则 END。用 Command 而非条件边的好处：路由逻辑和状态更新在一次原子操作里完成。

**`_tool_call` 节点（L187）**：取最后一条 AI 消息的 `tool_calls`；单个工具直接执行，多个用 `asyncio.gather` **并发执行**（L210）；每个结果包成 `ToolMessage(content, name, tool_call_id)`——`tool_call_id` 必须回填，LLM 靠它对号。然后 `goto="chat"` 回主循环（工具结果 → LLM 再思考 → 可能再调工具……）。注册时（L231）`retry_policy=RetryPolicy(max_attempts=3)`——**节点级重试**由 LangGraph 框架执行，工具抛错自动重试三次。

**`create_graph`（L214）**：`StateGraph(GraphState)` 两节点一循环：`chat ↔ tool_call`，entry 和 finish 都在 `chat`。L237-239：先拿连接池（失败即抛），`AsyncPostgresSaver(pool)` + **`await checkpointer.setup()`**（首次运行自动在 Postgres 建 checkpoint 表，**不需要 alembic**），`compile(checkpointer=...)` 完成。

**`get_response` 非流式（L268）**：对外主入口，三个关键机制：

1. `config["configurable"]["thread_id"] = session_id`——checkpointer 按 thread_id 隔离每个会话的状态，这就是"多轮记忆"的钥匙；
2. L302 `asyncio.gather(aget_state, memory.search)` ——**并发**做"查当前图状态"和"检索长期记忆"，注释说省 200-500ms；
3. **HITL 恢复判定**：`state.next` 非空 = 图停在某个 interrupt 上等待输入 → 用 `Command(resume=用户消息)` 恢复（L309），而不是当新输入；正常路径才走 `{"messages": ..., "long_term_memory": ...}`。调用完再查一次 `state.next`（L321），若这次又中断了，取出 interrupt 的 question 返回给前端（L325）。
   最后 `asyncio.create_task(memory.add(...))` fire-and-forget 写长期记忆。

**`get_stream_response` 流式（L339）**：同样的 gather + interrupt 判定，然后 `graph.astream(graph_input, config, stream_mode="messages")`——`messages` 模式直接产出 **LLM token 级事件**；L390 过滤只留 `AIMessage/AIMessageChunk`（跳过工具消息等），`extract_text_content` 提文本逐段 `yield`。流结束后同样处理中断检查 + 后台记忆写入。

**`get_chat_history`（L415）/`clear_chat_history`（L439）**：前者 `aget_state` 从 checkpoint 读全部消息（历史查询不需要业务表！）；后者对三张 checkpoint 表按 thread_id 做 **pipeline 批量 DELETE**（L455-461，一次网络往返删三表）。

**迁移改造**：落到 `backend/app/core/langgraph/graph.py`。适配清单：

1. **settings**：模板 `POSTGRES_*` 改读我们 config 的 DB 配置；注意我们的 SQLModel engine 是同步的，**不能复用**，独立异步池是必须的（模板原样保留即可）。
2. **分阶段裁剪引用**：`llm_inference_duration_seconds`（metrics）、`langfuse_callback_handler`（observability）、`memory_service`（memory）三个 import 在对应能力迁入前先删——把 metrics 计时换成空操作、memory 调用换成返回空串的 stub，第 4/5/6 步再接回。**建议直接做成可选注入**（如 `memory: MemoryService | None = None`），避免来回改。
3. **模型名取值**（L141-146 `get_llm().model_name`）：DeepSeek 模型对象同样有 `model_name` 属性，兼容。

**依赖**：`langgraph`、`langgraph-checkpoint-postgres`、`psycopg[binary]`（已有）+ psycopg_pool（随 langgraph-checkpoint-postgres 装）。

### 2.3 checkpoint 三张表（无源文件，运行时自建）

`checkpointer.setup()` 建的 `checkpoints` / `checkpoint_writes` / `checkpoint_blobs` 三表，配置侧只有一个 `CHECKPOINT_TABLES` 列表（`app/core/config.py` L194）供 `clear_chat_history` 拼删除语句。迁移时把这个列表抄进我们 config 即可，表本身随首次启动自动创建，无迁移脚本。多实例部署共享同一 Postgres 时天然共享会话状态。

---

## 第 3 步：对外接口

### 3.1 `app/api/v1/chatbot.py`（194 行）— 4 端点 + SSE

**它是干嘛的**：

- **`POST /chat`（L35）非流式**：`maybe_name_session`（起标题）→ `agent.get_response` → `ChatResponse`。
- **`POST /chat/stream`（L77）SSE 流式**：核心是内层 `event_generator`（L107）——每个 token 包成 `StreamResponse(content=chunk, done=False)`，`json.dumps` 后以 `data: {...}\n\n` 帧格式 `yield`；正常结束发 `done=true` 空帧（L125）；**异常也包成 `done=true` 的错误帧**（L134）而不是中断连接——保证前端任何情况下都能收到明确的结束信号，不会挂死等流。外层包 Prometheus 流式耗时。
- **`GET /messages`（L148）**：`agent.get_chat_history(session.id)` 从 checkpoint 读历史——**不需要业务侧消息表**，checkpointer 就是消息库。
- **`DELETE /messages`（L174）**：`clear_chat_history` 清三张 checkpoint 表。
- 模块级 `agent = LangGraphAgent()` 单例（L32），main.py lifespan 引用它预热。

**迁移改造**：落到 `backend/app/api/routes/chat.py`，改动最大的一步：

1. **鉴权对接**：模板用 `get_current_session`（per-session JWT，sub=session_id）。我们用 per-user JWT（`CurrentUser`/`SessionDep`），**必须新建 ChatSession 表**（`backend/app/models.py` + alembic 迁移：id、user_id 外键、name 默认空串、created_at），thread_id 用 `chat_session.id`。没有这张表，thread_id 只能拿 user_id 顶替——那用户所有对话会串成一串、无法清空单会话，不可取。会话 CRUD 端点（列表/改名/删除）可顺手加，或后续补。
2. **限流装饰器**先留空（`@limiter.limit` 等第 5 步 slowapi 迁入再补）。
3. SSE 在我们这边的注意点：`StreamingResponse` 与逐 token yield 的组合模板已验证可行；开发期用 `curl -N` 验证帧格式。

**依赖**：无新增（alembic 已有）。

---

## 第 4 步：记忆与体验

### 4.1 `app/services/memory.py`（103 行）— mem0 长期记忆

**它是干嘛的**：

- `_get_memory`（L20）：`AsyncMemory.from_config` 三段配置——**vector_store 用 pgvector**（连的就是同一个 Postgres，靠 collection 名隔离，不用另起向量库）、**llm** 用 nano 小模型（mem0 内部靠 LLM 从对话里**抽取**值得记的事实）、**embedder** 用 embedding 模型做语义检索。
- `search`（L56）：L65 `user_id is None` 直接返回空串——**匿名会话跳过长期记忆也不共享公共分区**，防止污染；先查缓存（cache_key 见第 5 步），miss 才问 mem0，结果拼成 bullet 列表，**只缓存成功结果**。
- `add`（L88）：对话结束后写入，异常只 log 不抛（记忆失败不应影响主流程）。
- `initialize`（L47）：启动预热，省掉首次 ~130ms 的 from_config + pgvector 建连冷启动。

**迁移改造**：落到 `backend/app/services/memory.py`。**本步最大的适配难点是 DeepSeek 没有 embedding API**：mem0 的 embedder 必须配一个真实的 embedding 服务——要么用 OpenAI 兼容的第三方端点（如 SiliconFlow 的 bge 系列或 OpenAI 官方），要么此步暂缓、先把 `memory_service` 做成可空 stub（graph.py 已按"可 None"设计）。llm 段可以直接指 DeepSeek（OpenAI 兼容协议，base_url + api_key 可注入 mem0 config）。DB 侧：Postgres 需要 pgvector 扩展——`CREATE EXTENSION vector` 或 compose 换 `pgvector/pgvector:pg16` 镜像 + 一个 alembic 迁移记录。

**依赖**：`mem0ai`；DB 加 pgvector 扩展。

### 4.2 `app/services/session_naming.py`（91 行）— 会话自动命名

**它是干嘛的**：首条消息触发三步曲：

1. **原子认领**（`_claim_session` L39）：`UPDATE sessions SET name=占位名 WHERE id=? AND name=''` 单语句——并发请求/多 worker 下**恰好一个**调用方拿到 `rowcount==1`，其余直接退出。用数据库行锁去重，不引入分布式锁。
2. **占位名**（`_build_placeholder` L34）：用户首条消息压空白取前 40 字符——LLM 失败也会有个可读标题。
3. **后台起名**（`_persist_session_name` L56）：`asyncio.create_task` 里调 nano 模型 + `response_format=SessionTitle`（结构化输出）+ `max_tokens=32` 生成正式标题覆盖。`_background_tasks` set 持引用防 GC，`add_done_callback(discard)` 用完自清。

**迁移改造**：落到 `backend/app/services/session_naming.py`。适配：我们的 llm registry 是单模型，去掉 `model_name="gpt-5.4-nano"` 和 `reasoning=` 参数，直接用主模型（DeepSeek 起个标题的开销可忽略）；`database_service.update_session_name` 换成我们的 SessionDep 写法；依赖第 3 步的 ChatSession 表（name 列默认空串）。`SESSION_NAMING_ENABLED` 开关抄进 config。

**依赖**：无新增。

---

## 第 5 步：生产加固

### 5.1 `app/core/cache.py`（213 行）— 缓存层

**它是干嘛的**：同接口双实现 + 工厂：

- `InMemoryCacheService`（L35）：`dict[key, (过期时间, 值)]`，用 `time.monotonic()` 判断过期（单调时钟不受系统改时间影响）；get 时惰性删除。
- `ValkeyCacheService`（L93）：redis.asyncio 客户端（Valkey 是 redis 协议兼容的竞品），`initialize` 时 `ping()` 验活；所有操作 try/except 降级为 warning——**缓存失败不阻塞业务**。
- `_create_cache_service` 工厂（L177）：配了 `VALKEY_HOST` 且装了 redis 包 → Valkey；配了没装 → warning 降级内存；没配 → 内存。`redis` 是**可选依赖**（try import，L20-32），装不装都能跑。
- `cache_key`（L197）：`prefix + sha256(拼接串)[:16]`——确定性、定长、无特殊字符。

**迁移改造**：基本照搬 `backend/app/core/cache.py`。VALKEY_* 六个配置项并入我们的 pydantic-settings config（`VALKEY_HOST` 默认空 = 内存模式，**起步可以完全不装 redis**）。memory.search 是第一个消费方（第 4 步迁移时若 cache 未到，先给 memory 一个内存版或 stub）。

**依赖**：`redis`（可选，`cache` extra）。

### 5.2 `app/core/limiter.py`（37 行）— 限流

**它是干嘛的**：slowapi 的 `Limiter` 实例化 + 存储选择：key 按**客户端 IP**（`get_remote_address`）；配了 Valkey 就拼 `redis://` 作 `storage_uri`——**分布式限流**，多实例共享计数才正确；没配则进程内存。每端点限额表在 `app/core/config.py` L208-224（chat 30/分钟、chat_stream 20/分钟、login 20/分钟……每个都能用 `RATE_LIMIT_<ENDPOINT>` 环境变量覆盖）。使用侧两个动作：路由加 `@limiter.limit(...)` 装饰器（**端点第一个参数必须是 `request: Request`**，slowapi 的硬要求）+ main.py 注册 `app.state.limiter` 和 `RateLimitExceeded` 异常处理器。

**迁移改造**：照搬 `backend/app/core/limiter.py`，限额表并入 config；给我们现有 `login.py`（防爆破）和新的 `chat.py` 路由补装饰器——注意补 `request: Request` 参数。

**依赖**：`slowapi`。

### 5.3 `app/core/metrics.py`（54 行）+ `prometheus/` + `grafana/` — 指标

**它是干嘛的**：两类指标：

- HTTP 层：`http_requests_total`（Counter）、`http_request_duration_seconds`（Histogram）——由 `starlette_prometheus` 的中间件 + `/metrics` 路由（`setup_metrics` L44 一行接入）自动采集；
- 业务层（手动埋点）：`llm_inference_duration_seconds` / `llm_stream_duration_seconds`（带 `model` 标签的耗时直方图，bucket 手工定制 0.1~5s / 0.1~10s）、`session_names_generated_total`（成功/失败计数）。埋点位置：graph.py L157 `.labels(model=...).time()` 包住 LLM 调用、chatbot.py L117 包住流式全程、session_naming L70/73 计数。

配套：`prometheus/prometheus.yml`（抓取配置）+ `grafana/dashboards/json/llm_latency.json`（现成 LLM 延迟看板）+ compose 里的 Prometheus/Grafana/cadvisor 服务。

**迁移改造**：`metrics.py` 照搬 `backend/app/core/metrics.py`；graph.py/chatbot.py 里第 2/3 步预留的空计时点接回真实现；prometheus/ + grafana/ 目录拷到仓库根，compose 加服务（我们已有 compose，加服务而非替换）。

**依赖**：`prometheus-client`、`starlette-prometheus`。

### 5.4 `app/core/logging.py`（261 行）— 真 structlog 日志

**它是干嘛的**：我们现有 `backend/app/core/logging.py` 是为了迁 LLM 工厂写的 **API shim**（模仿 structlog 的 `logger.info(event, **kwargs)`），模板这个才是真身：

- **ContextVar 请求上下文**（L34-58）：`bind_context(session_id=...)` 把键值挂进当前异步上下文，`add_context_to_event_dict` processor（L61）把它们自动合进**同请求内的每条日志**——排查"这个请求期间所有日志"时一键过滤。
- **correlation-id**（L80）：配合 `asgi-correlation-id` 的 `CorrelationIdMiddleware`，每条日志自动带 `request_id`，跨服务/跨日志文件串联一次请求。
- `JsonlFileHandler`（L107）：按日写 `logs/{env}-YYYY-MM-DD.jsonl`，一行一条 JSON。
- 环境自适应（L193）：`LOG_FORMAT=console` 用 `ConsoleRenderer` 彩色美化（开发），否则 `JSONRenderer`（生产）；`CallsiteParameterAdder`（文件名/行号）只开在 dev/test，生产日志瘦身。

**迁移改造**：**直接替换** `backend/app/core/logging.py`（shim 的 API 与 structlog 原生一致，已迁移的 llm service 零改动）。LOG_DIR/LOG_FORMAT/LOG_LEVEL 配置并入 config。

**依赖**：`structlog`、`asgi-correlation-id`。

### 5.5 `app/core/middleware.py`（212 行）— 中间件组

**它是干嘛的**：三个 `BaseHTTPMiddleware`：

- `MetricsMiddleware`（L49）：`finally` 里记请求数和耗时——**异常请求也记上 500**，不漏统计。
- `LoggingContextMiddleware`（L82）：解 Bearer JWT 把 session_id `bind_context` 进日志上下文；**只做日志用途不做鉴权**（token 无效时 pass，401 交给路由依赖处理——职责分离）；finally 里 `clear_context()` 防上下文泄漏到下一个请求。
- `ProfilingMiddleware`（L136)：仅 DEBUG 生效 + pyinstrument 可选导入；tracemalloc + CPU 时间 + 墙钟三路采样，请求超过阈值（默认 2s）写一份 JSON 报告（top 20 内存分配点 + 完整调用树）到 PROFILING_DIR，文件名用 correlation-id 可与日志对查。

**迁移改造**：照搬 `backend/app/core/middleware.py`。适配：JWT 解码改用我们 `core/security.py` 的凭据解码函数；模板 token 的 sub 是 session_id，我们的是 user id——`bind_context(user_id=...)` 语义微调。在 `backend/app/main.py` 按模板 main.py L94-104 的顺序注册（CorrelationIdMiddleware 必须最外层，request_id 要先于一切生成）。

**依赖**：`pyinstrument`（可选，DEBUG 才需要）。

---

## 第 6 步：可观测性收尾

### 6.1 `app/core/observability.py`（43 行）— Langfuse 追踪

**它是干嘛的**：`langfuse_init()` 启动时初始化 + `auth_check()` 验活（失败只 warning 不阻断启动）；`langfuse_callback_handler` 是 **LangChain CallbackHandler 单例**——graph.py L287/L357 在构造 `RunnableConfig` 时把它放进 `callbacks`，LangChain 体系内**每次 LLM 调用、每个工具执行、整图拓扑**自动上报 Langfuse，形成完整 trace 树（成本、延迟、token 数、prompt 全文）。代码量极小，威力全在回调机制。

**迁移改造**：照搬 `backend/app/core/observability.py`；`LANGFUSE_*` 四个配置并入 config（`LANGFUSE_TRACING_ENABLED` 默认 false 起步）。需要 Langfuse 实例：cloud 版注册即用，或自托管 compose 加服务。graph.py 第 2 步预留的 callback 注入点接回。

**依赖**：`langfuse==3.9.1`（模板锁了这个版本，跟随）。

### 6.2 `evals/`（5 文件 + 5 prompt，~750 行）— LLM-as-judge 评估

**它是干嘛的**：

- `main.py`（268 行）：CLI 入口，`--interactive`（每条确认）/`--quick`（默认配置直接跑）/`--no-report`。
- `evaluator.py`（219 行）：`Evaluator` L35——从 Langfuse 拉**最近 24h 未评分的 trace**（L203），对每条 trace × 每个指标调用 `openai.beta.chat.completions.parse`（**结构化输出**，schema 是 `schemas.py` 的 ScoreSchema：score 0~1 + reasoning），分数**写回 Langfuse**（L116）挂在原 trace 上。
- `metrics/__init__.py`（L5）：**自动发现** `metrics/prompts/*.md` 为指标——加一个评估维度 = 丢一个 md 文件，零代码。
- 五个现成指标 prompt：conciseness / hallucination / helpfulness / relevancy / toxicity，每个内含评分标准 + few-shot 正反例（如 hallucination.md 用"胡萝卜改善视力"的反例演示打 1.0 分的推理过程）。
- `helpers.py`：汇总 JSON 报告 + 成功率。

**迁移改造**：拷到 `backend/evals/`。依赖第 6.1 步（数据源是 Langfuse trace）；`EVALUATION_LLM` 配置可指 DeepSeek（OpenAI 兼容），但 `beta.chat.completions.parse` 需要 OpenAI SDK——用 DeepSeek 的 `response_format` json 模式替代或保留 OpenAI key 专用于评估。教学场景值得加两个自定义指标 prompt：如"答案是否基于课件内容（引用忠实度）""讲解是否适合学生水平"——丢 md 文件即可。

**依赖**：`tqdm`、`colorama`（openai 已有）。

---

## 附 A：`app/main.py` 装配与 lifespan（196 行）

不整体迁移（我们有自己的 main.py），但两段值得抄：

1. **lifespan 启动预热序列**（L41-79）：cache init → `agent.create_graph()` 预热（避免首请求冷启动建池建图）→ `memory_service.initialize()` 预热；关闭时 cache/pool 双清理。对应我们：第 2 步迁完在 lifespan 加 graph 预热，第 4 步加 memory 预热。
2. **中间件注册顺序**（L93-104）：LoggingContext 先于 Metrics，CorrelationId 最外层。
3. `/health` 的 DB 探活语义（L171-196）：DB 挂了返回 **503** 让负载均衡摘除实例，而非 200+degraded。

## 附 B：配置项并入清单（`backend/app/core/config.py`）

模板 config.py 本身**不搬**（它是 plain class + os.getenv + .env 文件级联，我们是 pydantic-settings，各有所长）。只并入新增字段：

| 配置组   | 字段                                                                    | 默认               | 随第几步 |
| -------- | ----------------------------------------------------------------------- | ------------------ | -------- |
| 图上下文 | `LLM_CONTEXT_TOKENS`（对应模板 MAX_TOKENS）                           | 2000               | 1        |
| 检查点   | `CHECKPOINT_TABLES`                                                   | 三表名单           | 2        |
| 会话     | `SESSION_NAMING_ENABLED`                                              | true               | 3/4      |
| 记忆     | `LONG_TERM_MEMORY_*`（model/embedder/collection）                     | —                 | 4        |
| 缓存     | `VALKEY_HOST/PORT/DB/PASSWORD/MAX_CONNECTIONS`、`CACHE_TTL_SECONDS` | 空（=内存模式）/60 | 5        |
| 限流     | `RATE_LIMIT_DEFAULT`、`RATE_LIMIT_ENDPOINTS`                        | 见 5.2             | 5        |
| 日志     | `LOG_DIR`、`LOG_FORMAT`、`LOG_LEVEL`                              | logs/json/INFO     | 5        |
| 剖析     | `PROFILING_DIR`、`PROFILING_THRESHOLD_SECONDS`                      | /tmp/2.0           | 5        |
| 追踪     | `LANGFUSE_TRACING_ENABLED/PUBLIC_KEY/SECRET_KEY/HOST`                 | false/…           | 6        |
| 评估     | `EVALUATION_LLM/BASE_URL/API_KEY/SLEEP_TIME`                          | —                 | 6        |

另有一个值得单抄的防御（模板 config.py L272 `validate_jwt_secret_key`）：**启动时拒绝空/短于 32 位/占位符 JWT 密钥**（WEAK_JWT_SECRET_KEYS 黑名单 L15）——我们 config 加一条 pydantic validator 即可，防止生产带默认密钥上线。

## 附 C：依赖汇总（按步骤执行 `uv add`）

| 步骤 | 新增依赖                                                                                                                                                |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1    | `langgraph`、`tiktoken`（模板漏声明，我们显式加）                                                                                                   |
| 2    | `langgraph-checkpoint-postgres`                                                                                                                       |
| 3    | —                                                                                                                                                      |
| 4    | `mem0ai`（+ Postgres 装 pgvector 扩展）                                                                                                               |
| 5    | `slowapi`、`prometheus-client`、`starlette-prometheus`、`structlog`、`asgi-correlation-id`、`redis`（可选 extra）、`pyinstrument`（可选） |
| 6    | `langfuse==3.9.1`、`tqdm`、`colorama`                                                                                                             |

已有可用：`langchain-core`、`langchain-openai`、`tenacity`、`psycopg[binary]`、`sqlmodel`、`alembic`、`openai`。

## 附 D：不迁移清单（含理由）

| 模板内容                                                        | 不迁理由                                                                                           |
| --------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `app/api/v1/auth.py`、`app/utils/auth.py`、`app/models/*` | 我们已有 per-user JWT + 用户体系（full-stack-fastapi 血统），模板的 per-session token 是另一套模型 |
| `app/services/database.py`                                    | **反面教材**：`async def` 端点里跑同步 SQLModel 调用，阻塞事件循环                         |
| `tools/duckduckgo_search.py`                                  | 公网搜索非教学场景；模式已由注册表承接                                                             |
| `app/models/thread.py`                                        | 模板自己都没在路由里用                                                                             |
| `supabase`、`psycopg2-binary`、`pydantic-settings` 依赖   | 模板声明了但代码没用                                                                               |
| Dockerfile/Makefile/CI 整体                                     | 我们已有部署体系；可日后参考其非 root 用户 + uv frozen 锁定 + detect-secrets 基线做法做加固        |

## 附 E：每步验收方式

| 步骤 | 验收                                                                                                                                     |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| 1    | pytest 单测：schema 校验（script 标签拒绝、长度边界）、prepare_messages 裁剪行为、prompt 注入变量渲染                                    |
| 2    | 后端起服务，脚本直调`agent.get_response`：多轮对话历史累积（同 thread_id）、换 thread_id 隔离、Postgres 里查到三张 checkpoint 表有数据 |
| 3    | `curl -N -X POST .../chat/stream` 看到 `data: {...}` 帧 + `done:true` 收尾；`GET/DELETE /messages` 行为正确；前端联调 SSE        |
| 4    | 同一 user 两段对话提到同一事实，第二段能被记住（`memory.search` 命中）；新会话标题自动生成                                             |
| 5    | `/metrics` 出现 LLM 延迟直方图；日志文件出现带 request_id/session 上下文的 JSONL；超过限额的请求返回 429                               |
| 6    | Langfuse 面板看到完整 trace 树；`uv run python -m evals --quick` 跑出五指标评分并回写                                                  |

---

*本文档基于模板源码逐文件精读整理（2026-09-16），行号对应当前 vendored 版本。迁移时如模板有更新，以重新核对为准。*
