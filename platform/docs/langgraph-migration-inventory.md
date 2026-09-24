# LangGraph 迁移范围与底层函数清单

核对日期：2026-09-16。源目录：`vendor/fastapi-langgraph-agent-production-ready-template/`；目标目录：`backend/`。

本轮用户确认：**先梳理范围与底层函数，形成详细方案，不继续实现业务代码。** 本文补充 [原逐文件迁移方案](langgraph-migration-plan.md)，以当前源码为准区分已存在的实现、尚缺内容和建议改造；“已有代码”不等于“已验收”。vendor 的版本记录见 [vendor/README.md](../vendor/README.md)，本文统计直接读取当前本地文件。

## 1. 到底涉及多少内容

这里的“模型广场”按仓库实际理解为已迁移的 `app/services/llm/` 模型注册表和调用工厂。本次核心是让它进入有状态的 Agent 工作流。

| 范围 | vendor 来源文件数 | 源码物理行数 | 自定义函数/方法定义数 | 内容 |
| --- | ---: | ---: | ---: | --- |
| A. 核心适配包 | 8 | 802 | 20 | 图、状态、消息模型、消息处理、提示词、工具注册表；包含预备给起标题用的模板 |
| B. 示例工具（可选） | 2 | 36 | 1 | 人工确认、DuckDuckGo 搜索 |
| C. 聊天产品能力 | 4 | 601 | 28 | 聊天 API、记忆、自动标题、缓存 |
| D. 生产运行配套 | 5 | 607 | 17 | 日志、指标、中间件、限流、Langfuse |
| A–D 合计 | **19** | **2046** | **66** | 不含已迁移的模型工厂及下面列出的装配/业务适配工作 |
| E. 离线评估（可选） | 10 | 单独排期 | 28 | 5 个 Python 文件和 5 个评分提示词 |

统计规则：行数包含注释和空行；函数数按 Python AST 的 `def/async def` 计数，含构造方法、嵌套函数和校验器，不含第三方库内部实现。表格是**来源规模，不是待新增代码量或工期**。A 中 `session_title.md` 可随标题功能后移；B 的搜索包装没有自定义函数。

此外必须适配现有 `config.py`、`main.py`、API 路由装配、依赖锁文件和测试；如果接入业务，还要补会话模型、Alembic 迁移、权限检查及前端协议。因此不能把“复制 19 个文件”作为完整迁移的定义。

**建议分界：先完成 A 的核对与验收，再接入聊天会话和现有章节问答；记忆、标题、监控、评估按需追加。** 模板里的两个示例工具是否保留是产品选择；当前实现和原方案均采用空工具表，本轮不改变这一取舍。

## 2. 当前项目已经有什么

| 项目 | 当前证据 | 状态 |
| --- | --- | --- |
| 模型工厂 | `backend/app/services/llm/{registry,service,__init__}.py` | 已存在，复用 |
| 状态、聊天模型 | `backend/app/schemas/{graph,chat}.py` | 已存在 |
| 消息处理五个函数 | `backend/app/core/langgraph/utils.py` | 已存在 |
| 提示词三文件 | `backend/app/core/prompts/` | 已存在，已增加章节上下文 |
| Agent 核心 | `backend/app/core/langgraph/graph.py` | 已存在，包括响应、流式、历史、清空和关闭 |
| 工具注册 | `backend/app/core/langgraph/tools/__init__.py` | 已存在，但列表为空；没有实际业务工具 |
| 检查点装配 | `config.py` 的两个 CHECKPOINT 字段、`main.py` lifespan | 已存在，启动预热并在正常退出时关闭 |
| 依赖 | `backend/pyproject.toml` | 已声明 `langgraph`、`tiktoken`、`langgraph-checkpoint-postgres` |
| 测试代码 | `tests/core/` + `tests/schemas/` 五个测试模块 | 静态统计 34 个测试函数，不代表本轮通过 34 项 |
| 验收脚本 | `backend/scripts/verify_langgraph_agent.py` | 已存在，会连接数据库、调用真实 LLM、清理指定测试 thread |
| 章节问答 | `backend/app/api/routes/ask.py` | 仍直接调用 `llm_service.call`，尚未走图 |
| 会话 API / ORM | `backend/app/api/main.py`、`models.py` | 尚无新聊天路由和 ChatSession 模型 |
| 长期记忆、标题服务 | 目标 `services/memory.py`、`services/session_naming.py` | 尚未实现；图只预留可选记忆接口 |
| 完整可观测性 | 图中 `nullcontext()`、空 callbacks、现有 logging shim | 指标和追踪尚未接回 |

原方案顶部仅记录“第 1 步完成”，但工作区已存在第 2 步实现。应将其理解为“第 1、2 步已有代码，第 2 步仍需按验收记录核实”，不能据旧标题重复重写。

## 3. 一次请求的完整调用链

```text
用户 JWT → 我们的 CurrentUser → 校验 ChatSession 所属用户与章节访问权
  → chat / chat_stream
    ├─ 可选：maybe_name_session → _claim_session → 后台 _persist_session_name
    └─ LangGraphAgent.get_response / get_stream_response
       ├─ _get_graph → create_graph → _get_connection_pool
       │                            → AsyncPostgresSaver.setup / compile
       ├─ graph.aget_state(thread_id)
       ├─ 可选：MemoryService.search → cache_key / cache.get
       │                             → _get_memory → mem0.search → cache.set
       ├─ 新请求：messages + long_term_memory
       │  中断恢复：Command(resume=用户答复)
       └─ graph.ainvoke / graph.astream
          └─ _chat
             ├─ load_system_prompt（用户、时间、章节、记忆）
             ├─ prepare_messages → dump_messages → trim_messages
             │                                    → _count_tokens_tiktoken
             ├─ llm_service.call
             │  → _call_with_fallback → _fallback_loop → _invoke_with_retry
             │  → 模型 ainvoke；必要时 _switch_to_next_model
             ├─ process_llm_response → extract_text_content
             └─ 有 tool_calls → _tool_call → _execute_tool → 工具.ainvoke
                                  → ToolMessage → 回到 _chat
                无 tool_calls → END
       → 同步结果：__process_messages
         流式结果：extract_text_content → event_generator → SSE
       → 可选后台：MemoryService.add → _get_memory → mem0.add

历史读取：get_session_messages → get_chat_history → aget_state → __process_messages
清空历史：API clear_chat_history → Agent.clear_chat_history → 数据库按 thread 删除
关闭应用：lifespan → Agent.close（以及后续缓存、追踪、后台任务清理）
```

这里的 `thread_id` 是会话状态分区标识，不是权限凭据。`user_id` 放进 graph metadata 也不会自动产生数据访问控制，鉴权必须在调用 Agent 之前完成。

## 4. 核心 8 文件，逐个函数怎么迁

以下来源路径相对 vendor 根目录，括号为核对时行号。

### 4.1 `app/core/langgraph/graph.py`：474 行、12 个定义

目标：`backend/app/core/langgraph/graph.py`。已有移植，后续以补缺和验证为主。

| 自定义方法 | 做什么 / 调用的底层能力 | 适配要求 |
| --- | --- | --- |
| `__init__`（73） | 引用模型工厂，`bind_tools(tools)`，建立 `tools_by_name`，初始化 pool/graph | 空表跳过绑定已有；后续多个 Agent 使用不同工具集时，应隔离可变 LLMService 实例 |
| `_get_connection_pool`（87） | 建异步 psycopg pool，设置 autocommit、dict_row、连接超时等 | 已改读本项目 DATABASE_URL 和 CHECKPOINT_POOL_SIZE；补失败清理与并发初始化验证 |
| `_chat`（130） | 组提示词、裁剪消息、调用工厂、处理结果，返回 Command 路由 | 已传 chapter_context；保留消息的 tool_calls 等结构，接回可选指标 |
| `_tool_call`（187） | 从最后一条 AI 消息取工具调用，执行后回到 chat | 验证未知工具、无效参数、并行错误、工具结果序列化及重试边界 |
| 嵌套 `_execute_tool`（198） | `tools_by_name[name].ainvoke(args)` → ToolMessage | **它也是必须迁的自定义函数**；tool_call_id 必须匹配原调用 |
| `create_graph`（214） | 建 StateGraph、注册 chat/tool_call、RetryPolicy、建检查点并 compile | 明确有向边与 Command 路由；编译失败释放已分配资源；数据库不可用时启动失败是本项目策略 |
| `_get_graph`（257） | 惰性取得编译后的图 | 与启动预热复用同一实例，避免路由另建 Agent |
| `get_response`（268） | 取状态/记忆、新输入或恢复、同步执行、后台写记忆、输出转换 | 验证非空输入；恢复判断读取真实 interrupt 信息；输出契约需区分全历史和本轮回答 |
| `get_stream_response`（339） | messages 流，筛 AI chunk，提取文本，结束后检查中断和写记忆 | 不是自己拼假的 token；验证供应商流式能力、异常、取消与中断事件 |
| `get_chat_history`（415） | 按 thread 读状态，再过滤转换 | 路由先鉴权；不存在的会话与空历史要区分 |
| `__process_messages`（430） | convert_to_openai_messages 后保留 user/assistant 且有内容的消息 | 工具消息仍留在内部状态；输出不能继续受输入 3000 字符限制 |
| `clear_chat_history`（439） | 通过连接池 pipeline 批量 DELETE 三张业务数据表 | 参数化 thread_id，表名用 sql.Identifier；清空与同会话生成需协调，明确事务语义 |

目标额外已有两个适配函数：`_checkpointer_conninfo()` 将 SQLAlchemy DSN 转为 psycopg 连接串；`close()` 关闭 pool 并清除编译图。另有 `MemoryServiceProtocol.search/add` 两个接口声明，**接口不是记忆服务实现**。

### 4.2 `app/utils/graph.py`：138 行、5 个定义

目标：`backend/app/core/langgraph/utils.py`，避免与现有单文件 `app/utils.py` 冲突。

| 自定义函数 | 输入 → 输出 / 调用方 | 必须保留或修正的行为 |
| --- | --- | --- |
| `_count_tokens_tiktoken`（18） | 消息列表 → 近似 token 数；由 trim_messages 回调 | 模块级编码器缓存；未知模型退到 cl100k_base；当前未完整计入工具 schema/工具参数及所有块类型 |
| `dump_messages`（42） | Pydantic/LangChain 消息 → model_dump 字典列表 | 不能只取 role/content 丢失 tool_calls、tool_call_id、id；验证序列化后可被模型识别 |
| `extract_text_content`（54） | str 或 content 块列表 → 纯文本 | 支持文本块，跳过 reasoning；流式和同步路径共用 |
| `process_llm_response`（86） | BaseMessage → content 规范化后的消息 | 保留 AIMessage 类型及工具调用结构；当前会原地改 content |
| `prepare_messages`（105） | 历史 + system prompt → 发给模型的消息 | 调 dump_messages、trim_messages 和计数函数；最近消息优先；不要破坏工具调用/结果配对 |

当前裁剪参数是 `strategy='last'`、`start_on='human'`、`include_system=False`、`allow_partial=False`。未知内容块触发特定 ValueError 时会退回全部历史。**这不是严格的总输入 token 上限**：system prompt 是裁剪后才前置的，课件、记忆及工具 schema 也要占预算。建议后续明确“模型总窗口 − 输出预留 − 系统/课件/记忆/工具开销 = 历史预算”，对无法计数的情况设置可验证的退路。

### 4.3 `app/schemas/{graph,chat}.py`：18 + 107 行、2 个定义

目标同名 schemas 包。

- `GraphState.messages` 使用第三方 `add_messages` reducer 合并消息；`long_term_memory` 保存本次检索结果。
- `Message.validate_content`（chat.py:33）拒绝匹配到的 script 标签和空字节；原 content 限长 1–3000。它只是内容校验，不代替前端 HTML 转义。
- `ChatRequest`、`ChatResponse`、`StreamResponse` 是输入、同步输出和 SSE 帧；本项目已经去掉模板 BaseResponse 包装。
- `SessionTitle._normalize`（chat.py:103）清理空白和首尾标点，拒绝归一化后的空标题；有 60 字符上限。

建议将“外部用户输入”“内部消息”“模型输出”拆开：外部输入可限长且仅允许 user；内部使用 LangChain 消息类型；输出允许正常的较长回答。不能用同一个输入模型校验系统提示词和所有历史回答。

### 4.4 `app/core/prompts/`：3 文件、52 行、1 个定义

- `__init__.py`（27 行）：模块加载时缓存两个模板；`load_system_prompt`（19）注入助手名、用户名、当前时间和记忆。本项目已增加 chapter_context。
- `system.md`（15 行）：改成学习助教规则与上下文占位符，已有实现。
- `session_title.md`（10 行）：仅标题服务需要，已有模板但没有服务。

迁移时验证模板文件包含在构建产物中，运行时不依赖 vendor 路径。

### 4.5 `app/core/langgraph/tools/__init__.py`：13 行、0 个定义

注册表本质是 `list[BaseTool]`；图构造时绑定给 LLM，同时建立按名称调用的字典。本项目为空列表，具备工具调度框架，但不具备任何已注册的教学工具。

示例工具单列而不冒充框架必需内容：

- `ask_human.py`：26 行，`ask_human(question)`（12）调用库的 `interrupt(question)`；开启它还需 UI 展示问题、独立的恢复请求和中断状态协议。
- `duckduckgo_search.py`：10 行，只有 `DuckDuckGoSearchResults(...)` 实例封装；如保留，再按实际包依赖补搜索依赖。
- 将来新增“读课件、检索课程”等工具必须实现具体函数，并把用户和课程权限带入执行环境；现有空表不算完成这些能力。

## 5. 已迁移的模型工厂：调用到底还经过什么

这些内容复用现有 `backend/app/services/llm/`，不重复搬运。

| 函数 / 方法 | 作用 |
| --- | --- |
| `LLMRegistry.get` | 根据模型名取实例；带参数时创建覆盖配置的实例 |
| `get_all_names` / `get_model_at_index` | 提供模型名和降级顺序 |
| `LLMService.__init__` | 设置当前模型、下标和绑定工具 |
| `call` | 统一入口、总超时控制；可返回普通消息或结构化 schema |
| `get_llm` / `bind_tools` | 取当前模型、绑定工具；绑定会修改共享服务状态 |
| `_call_with_fallback` | 根据默认调用或参数覆盖构造执行策略 |
| 嵌套 `_override_target` / `_default_target` | 取得临时模型或当前默认模型；前者可包装结构化输出 |
| 嵌套 `_override_advance` / `_default_advance` | 推进临时下标或共享模型下标 |
| `_fallback_loop` | 遍历注册模型直到成功或全部失败 |
| `_invoke_with_retry` | 使用 tenacity 对指定 API 错误重试，然后调用模型 ainvoke |
| `_switch_to_next_model` | 切换默认模型并重新绑定工具 |

默认调用使用带工具的模型；传 model_name / response_format / model_kwargs 会进入另一条实例构造路径。未来按 Agent 选择模型时，要验证该路径是否带着期望的工具，不能只认为“call 都一样”。本轮不改此前约定保留的工厂源码。

## 6. 聊天 API 与会话数据：不能漏掉的业务底层

来源 `app/api/v1/chatbot.py`：194 行、5 个定义。

| 函数 | 底层调用 | 目标处理 |
| --- | --- | --- |
| `chat`（37） | maybe_name_session → Agent.get_response | `backend/app/api/routes/chat.py`；使用 CurrentUser 与会话所有权检查 |
| `chat_stream`（79） | 返回 StreamingResponse | 响应头发出前完成认证和会话校验 |
| 嵌套 `event_generator`（107） | Agent.get_stream_response → JSON SSE 帧 | 文本、完成、错误和中断须可区分；异常不直接泄露内部错误详情 |
| `get_session_messages`（150） | Agent.get_chat_history | 查自己的会话 |
| API `clear_chat_history`（176） | Agent.clear_chat_history | 清除指定会话状态；与删除会话、删除长期记忆是不同操作 |

模板 `get_current_session` 在 `app/api/v1/auth.py:105`，依赖其会话 token、`verify_token`、`sanitize_string`、数据库会话查询和日志上下文；**整套认证不搬，使用我们的 CurrentUser 替代**。`utils/sanitization.py` 的 `sanitize_string`、`sanitize_email`、`sanitize_dict`、`sanitize_list`、`validate_password_strength` 不在图的消息处理调用链上，不必为了图导入整个 utils 包。

但“不搬 auth.py”不等于丢掉里面的会话 CRUD。模板把 `create_session`、`update_session_name`、`delete_session`、`get_user_sessions` 路由放在 auth.py；这些业务能力要在我们的会话路由重新落地。

建议新增 `ChatSession`：UUID 主键、user_id 外键、可选 chapter_id、name、created_at、updated_at。会话 ID 转成字符串作为 thread_id。章节绑定会话要同时验证章节访问权限；通用聊天可让 chapter_id 为空。会话表由 Alembic 管理，checkpoint 表由库管理。

建议将模板 `DatabaseService` 的以下职责收敛到 `backend/app/services/chat_sessions.py`（拟新增名称），使用本项目数据库体系：

| 底层函数职责 | 模板来源 | 必须实现的差异 |
| --- | --- | --- |
| 创建会话 | `create_session`（database.py:134） | 服务端生成 ID，绑定 current_user，校验章节 |
| 取会话并鉴权 | `get_session`（175） | 查询条件包含 owner，不能只凭 session_id |
| 列出会话 | `get_user_sessions`（188） | 按用户过滤，支持分页和更新时间排序 |
| 改标题 | `update_session_name`（204） | 校验所有权；自动标题不得覆盖用户后来手改的标题 |
| 删除会话 | `delete_session`（156） | 协调 checkpoint 清理、后台任务和并发生成，失败可重试 |
| 原子认领标题 | `_claim_session`（session_naming.py:39） | 保留条件 UPDATE 防重复；单独处理 DB I/O，不让同步事务阻塞 async 事件循环 |

不要整体复制模板数据库服务：其多个 async 方法内部仍使用同步 SQLModel Session。采用本项目同步服务在线程池运行，或为这部分显式建立异步仓储，二选一并保持事务边界清楚。

章节问答还要复用我们已有 `_get_accessible_course`、`_strip_html`、`_classroom_context` 和课件快照选择逻辑：教师编辑版 → LMS 快照 → 旧任务 OpenMAIC 回退，学生只能看到已发布内容。建议旧 `/ask/chapters/{id}` 保持兼容，新增会话 API 先跑通再切换前端。

请求建议每次只提交本轮新消息；历史由 checkpoint 加载。反复发送全量历史且不带稳定消息 ID，可能被 add_messages 当作新消息再次累积。不要开放让客户端任意提交 system/assistant 消息冒充服务端历史的通道。

## 7. 长期记忆和缓存：完整底层清单

### 7.1 `app/services/memory.py`：103 行、5 个定义

| 方法 | 调用链及适配 |
| --- | --- |
| `__init__`（16） | 缓存 `_memory` 实例 |
| `_get_memory`（20） | `AsyncMemory.from_config`；配置 pgvector、抽取用 LLM、embedding 模型；改读我们的 DB 和模型配置 |
| `initialize`（47） | 调 `_get_memory` 预热；只在启用记忆时装配 |
| `search`（56） | user_id 为空则跳过；cache_key → cache.get → mem0.search → 文本格式化 → cache.set；失败返回空字符串 |
| `add`（88） | user_id 为空则跳过；_get_memory → mem0.add；记录写入异常 |

**mem0 内部 LLM/embedding 没有经过我们的 LLMService。** 只搬 memory.py 不能自动共享模型工厂的网关、密钥、重试或降级。要么显式配置 mem0 provider 的连接参数，要么另做 provider 适配。聊天模型和 embedding 是两项配置，不能假定当前聊天网关支持所选 embedding 模型。

记忆按用户跨会话共享，checkpoint 按会话保存，两者各自管理。新增缓存失效、记忆删除语义与后台任务回收；避免每轮无条件重复抽取全部历史，评估按新增消息写入或去重。章节上下文已放入 metadata，接回记忆时应筛选 metadata，不能直接持久化整个课件文本。

### 7.2 `app/core/cache.py`：213 行、14 个定义

| 自定义函数 / 方法 | 职责 |
| --- | --- |
| `InMemoryCacheService.__init__ / initialize` | 设置 TTL、初始化本进程缓存 |
| `InMemoryCacheService.get / set / delete / close` | 带过期时间的读写、删除和清空 |
| `ValkeyCacheService.__init__ / initialize` | 设置客户端，通过 Redis 协议连接和 ping |
| `ValkeyCacheService.get / set / delete / close` | 缓存读写、失败降级和连接关闭 |
| `_create_cache_service`（177） | 根据配置与 Redis 依赖可用性选择实现 |
| `cache_key`（197） | 对 user_id、query 等参数做摘要并加前缀 |

**修正旧迁移顺序**：memory.py 导入 cache.py，不能第 4 步搬记忆、第 5 步才提供任何缓存实现。建议先随记忆提供内存缓存/可注入缓存接口，分布式 Valkey 后加。内存实现还应增加容量控制，原模板只在读取某个过期键时移除它。

## 8. 自动标题：4 个函数也要一起迁

来源 `app/services/session_naming.py`：91 行。

| 函数 | 内部职责 | 适配 |
| --- | --- | --- |
| `_build_placeholder`（34） | 压缩空白，截取 40 字符，空值兜底 | 可中文化默认标题 |
| `_claim_session`（39） | `UPDATE ... WHERE name = ''`，通过 rowcount 原子认领 | 替换模型/数据库入口；解决异步入口内同步 DB I/O |
| `_persist_session_name`（56） | 调 llm_service.call，结构化 SessionTitle，写 DB，记录指标 | 去掉写死的 gpt-5.4-nano 和不适配的 reasoning 参数；使用可配置且已注册模型 |
| `maybe_name_session`（77） | 找首条 user 消息、认领、建后台 task、完成后从集合移除 | 在会话创建与首次消息流程接入；关机处理任务，防止会话删除后再写入 |

复用已迁 `SessionTitle._normalize` 与 `SESSION_TITLE_PROMPT`。结构化输出能力需用配置模型验证；失败保留占位标题。原子认领只防止重复自动任务，不自动防止覆盖用户手工改名，持久化时还需条件更新。

## 9. 日志、指标、限流和追踪的底层函数

它们属于可分阶段装配的生产配套，不是所有图运行都必须依赖的模块。

| 来源 | 自定义函数 / 对象 | 迁移方式 |
| --- | --- | --- |
| `core/logging.py` | `bind_context`、`clear_context`、`get_context` | 请求级上下文隔离；已有 EventLogger 只满足基础记录，不含这些能力 |
| 同上 | `add_context_to_event_dict`、`add_request_id_to_event_dict` | 将上下文和 correlation ID 注入事件 |
| 同上 | `get_log_file_path`、`JsonlFileHandler.__init__/emit/close` | JSONL 落盘和句柄清理；适配部署日志目录 |
| 同上 | `get_structlog_processors`、`setup_logging` | 配置格式化和日志管道，保留工厂 logger 调用兼容性 |
| `core/metrics.py` | `setup_metrics`；`llm_inference_duration_seconds`、`llm_stream_duration_seconds`、`session_names_generated_total` 等对象 | 创建指标、挂中间件和 /metrics；图和标题接回埋点；订单示例指标不搬 |
| `core/middleware.py` | `MetricsMiddleware.dispatch` | 指标标签用路由模板，避免 UUID 路径产生高基数 |
| 同上 | `LoggingContextMiddleware.dispatch` | 用本项目认证后的用户信息；模板把 JWT sub 当 session_id，与我们体系不同，不能照搬 |
| 同上 | `ProfilingMiddleware.dispatch` | 调试可选；检查并发下进程级 tracemalloc 生命周期及异常清理 |
| `core/limiter.py` | 无自定义函数，模块级 limiter 和存储 URI 构造 | 保留接口级限流，验证代理 IP 和多 worker 存储方式 |
| `core/observability.py` | `langfuse_init`、`get_langfuse_callback_handler` | 仅开启追踪时初始化、注入 callback，关机 flush；模板在模块导入时就创建 callback，迁移时需解除这一强耦合 |

现有日志 shim 的 `_format` 与 `EventLogger.debug/info/warning/error/exception/log` 已能支持图和工厂的基础调用，本轮无需为列出完整函数就替换它。

## 10. 离线评估的边界

如果目标是迁完模板的评估能力，还涉及 `evals/` 的 10 个文件：

- `evaluator.py`：`Evaluator.__init__`、`run`、`_push_to_langfuse`、`_run_metric_evaluation`、`_call_openai`、`__fetch_traces` 六个方法，负责拉 trace、请求评分模型和回写评分。
- `helpers.py`：`format_messages`、`get_input_output`、`initialize_report`、`initialize_metrics_summary`、`update_success_metrics`、`update_failure_metrics`、`process_trace_results`、`calculate_avg_scores`、`generate_report` 九个函数。
- `main.py`：`print_title`、`print_info`、`print_warning`、`print_error`、`print_success`、`get_user_input`、`get_yes_no`、`display_summary`、`run_evaluation`、`display_configuration`、`interactive_mode`、`quick_mode`、`main` 十三个函数。
- `schemas.py` 的评分模型、`metrics/__init__.py` 的提示词加载，以及 helpfulness、relevancy、hallucination、toxicity、conciseness 五份提示词。

这条评估链使用独立 OpenAI 客户端和 EVALUATION 配置，不经过已迁模型工厂。它依赖已有 trace，建议最后迁。当前 vendor 没有 `evals/__main__.py`，原方案的 `python -m evals --quick` 不能直接照用；应使用 `python -m evals.main --quick`，或迁移时增加入口。

## 11. 第三方能力与我们自己要写的边界

| 第三方 API | 不必重写的部分 | 我们必须负责的部分 |
| --- | --- | --- |
| StateGraph / Command / add_messages / RetryPolicy / interrupt | 图调度、状态合并、恢复原语 | 节点、边、状态 schema、恢复协议、工具幂等和权限 |
| AsyncPostgresSaver / psycopg pool | checkpoint 存取、表迁移、池管理原语 | DSN、启动关闭、错误处理、thread 归属、删除协调 |
| trim_messages / convert_to_openai_messages / tiktoken | 消息转换、裁剪算法、编码器 | 预算、计数回调、结构化内容处理和业务输入输出模型 |
| mem0 AsyncMemory | 记忆抽取、检索与存储接口 | provider 配置、用户隔离、缓存、后台写入和删除策略 |
| FastAPI StreamingResponse / asyncio | HTTP 流和异步调度 | SSE 帧协议、取消/错误/完成语义、任务生命周期 |
| Langfuse / Prometheus / SlowAPI | 追踪、指标、限流库 | 配置与开关、回调注入、埋点和中间件装配 |

“底层函数一起迁”应指把模板自己的调用依赖补齐，不能靠空函数绕过；不需要复制 LangGraph、LangChain 或 mem0 的库源码。

## 12. 接入前必须解决的已知缺口

以下是静态源码核对结论或明确待验证项，本轮未执行运行时复现：

1. **提示词和输出长度冲突**：prepare_messages 用 content 最大 3000 的 Message 构造系统消息；章节抽取可达 8000 字符。长提示词会遇到校验限制；长模型回答经 __process_messages 也可能失败。拆分输入与内部/输出模型优先处理。
2. **图没有业务入口**：main.py 预热不等于 ask.py 已经走图。会话路由、ChatSession、权限和前端接入尚缺。
3. **中断判断过宽**：当前将 state.next 非空都当作 interrupt，并直接访问 tasks[0].interrupts[0]。错误留下的待执行节点不一定有人机中断；应按真实 interrupts 查找，支持多个中断并避免空索引。
4. **示例工具重试风险**：工具节点的 RetryPolicy 可能重跑整个节点。并行工具中一个失败时，已成功的有副作用工具不能重复执行；需限定可重试异常、幂等键或调整节点执行设计。
5. **共享模型服务可变**：多个 Agent 绑定不同工具会改同一个 llm_service；新增工具还可能影响仍直调工厂的 ask.py。接入业务工具前隔离实例或绑定状态。
6. **资源失败路径未完整覆盖**：当前 lifespan 的 close 在 yield 后直线执行，缺 try/finally；setup/compile 失败也可能留下已打开 pool。成功启动/正常退出测试不足以证明异常清理。
7. **预算并非总窗口限制**：系统、课件、记忆和工具开销尚未纳入；未知块退回所有历史会绕过裁剪。
8. **三张表并非全部建表**：本地安装的 postgres checkpointer 源码还创建 checkpoint_migrations 管理表。按 thread 删除的是 checkpoints、checkpoint_blobs、checkpoint_writes 三张数据表，不应清空管理表。并非每种执行都保证每张表都有有效载荷数据，验收以真实 checkpoint 恢复为主。
9. **启动策略描述需纠正**：vendor 图方法会抛初始化错误，但 vendor main.py 捕获预热异常后继续启动；我们当前 main.py 传播错误、拒绝启动。后者是本项目主动选择，不应写成完全照搬模板行为。
10. **测试说明与 pytest 装配不同**：图单测主体用了 stub，但顶层 tests/conftest.py 会加载 app 并启用自动 DB fixture。不能仅凭单测文件注释宣称运行它们不需数据库。

## 13. 推荐实施批次与验收

| 批次 | 具体交付 | 完成标准 |
| --- | --- | --- |
| 1. 核心收口 | 核对已有 A 类实现；修正输入/内部/输出模型、资源生命周期、中断分支、上下文预算；保持无实际工具也能运行 | 离线测试覆盖节点路由、完整工具往返、工具消息配对、长课件/长回答、失败清理、真实中断恢复；不会调用外部 LLM |
| 2. 状态持久化 | 使用隔离测试库验收 checkpoint、进程重建、线程隔离和清空 | 同会话历史累积；不同会话隔离；关闭重建后可恢复；DB 故障符合启动策略；不把每表必须有行作为唯一判断 |
| 3. 业务入口 | ChatSession + Alembic + 会话服务/路由；适配章节上下文和 SSE；复用主项目认证 | 两个用户不能访问彼此会话；章节权限生效；流正常/错误/取消均正确收尾；旧章节问答兼容 |
| 4. 标题与记忆 | 标题四函数 + 会话 DB 更新；最小缓存先落地，再迁 MemoryService，显式注入图 | 并发只认领一次标题；手改标题不被覆盖；记忆按用户隔离；失败不阻塞主对话；关闭回收后台任务 |
| 5. 运维配套 | 日志、限流、指标、可选 Valkey 与 Langfuse | callback 关闭时不初始化外部追踪；请求日志不串用户；指标可采集；配置限额返回 429 |
| 6. 评估 | evals、独立评分配置、运行入口 | 已有 trace 可评分、报告可生成、评分可回写；失败统计正确 |

依赖按批次声明：核心三项已在 pyproject；记忆需要 mem0ai 和可用 pgvector；缓存分布式模式需要 Redis 客户端；运维再补 structlog、slowapi、prometheus-client、starlette-prometheus、asgi-correlation-id、langfuse 等；评估再补 tqdm/colorama。版本以主项目锁文件和 Python >=3.14 的实际兼容验证决定，本轮不升级、不安装。

前端若要可用聊天体验，另列会话列表、创建/切换/删除、历史加载、SSE 增量显示、错误提示和可选中断确认 UI。vendor 这套后端没有可直接替换我们学习界面的前端实现，不能记作“后端文件迁完即可交付前端”。

## 14. 本轮交付与验证范围

- 已完成 vendor 与 backend 的静态调用链核对、AST 文件/函数计数、现有测试代码盘点及依赖缺口分析。
- 未修改应用代码、未运行数据库迁移、未调用真实模型、未运行验收脚本或应用测试。
- 原工作区已有未提交业务代码，全部保留。后续实施应从这些已有实现继续，而非从空目录重迁。

实施前仍属产品选择的事项：是否保留两个示例工具、是否首期包含长期记忆/标题、是否一章多会话、是否提供人工确认 UI。上文已给出可分批方案，不将这些选择当作本轮调研阻塞条件。
