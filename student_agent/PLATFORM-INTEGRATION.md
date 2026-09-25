# PLATFORM-INTEGRATION（学生 Agent 平台适配清单）

遵循与教师 Agent 相同的可平移性约定（见教师仓库 PLATFORM-INTEGRATION.md）：
平台语义只放独立模块，业务文件只留最小挂钩，逐条登记，上游更新时按清单重放。

## 独立模块（整文件平移）

| 文件 | 职责 |
|---|---|
| `apps/integration/`（10 个模块） | 平台适配层：`launch_context`（令牌 HMAC 校验）、`course_adapter`（已发布内容→课程计划）、`platform_client`（回调平台取学习上下文）、`persistence`（学情写 student schema）、`prompt_context`（已发布内容→有界提示词/题目/提示）、`models`/`config`/`evaluation`/`player_bridge` |
| ~~`apps/platform_adapter.py`~~ | **已废弃（死代码）**：全仓零 import，功能由 `apps/integration/launch_context.py` 取代。保留仅为历史参考，新代码不要引用 |
| `scripts/dev-8000-platform.ps1` | 平台启动学生端的入口（`platform/scripts/start-local.ps1` 直接调用；**丢失会让平台启动脚本 fail-fast 抛错**） |
| `scripts/verify_student_entry.py` | 可信入口验收脚本（发布链路搭建 + 8 项检查），用平台 venv python 运行 |
| `frontend/src/platform/playerAdapter.js` | 播放器 iframe 适配器：嵌入教师端 `/teacher/classroom-player/{id}`（Caddy 剥前缀），监听 SCENE_COMPLETED / PLAYBACK_ENDED postMessage（校验 origin+classroomId，按 eventId 幂等），映射到学生 Agent 的 media_done。教师端需配置 `NEXT_PUBLIC_SAAS_HOST_ORIGIN`（事件目标）与 `ALLOWED_FRAME_ANCESTORS`（CSP 嵌入许可），均为构建期内联 |

## 业务文件挂钩

| 文件 | 挂钩 | 说明 |
|---|---|---|
| `apps/server.py` | `StartIn.launch_token`；`/api/session/start` 令牌分支：验证→身份以令牌为准（调用方 `student_id` 被忽略）→ publication version 固定进会话 | 401/502/503 错误映射；`_persist_session_record` + `session_started` 事件 |
| `apps/server.py` | `_step` 里 `platform`/`learning_context` 每轮回注（LangGraph 只保留 TypedDict 的键） | 三处循环；另有学情同步块与两个幂等游标 `_persisted_message_seq` / `_completion_persisted` |
| `apps/server.py` | `_record_learning_event` / `_persist_session_record` / `_persist_lesson_completion` / `_preload_disk_sessions` | 学情落库；失败不阻塞课堂 |
| `apps/server.py` | 事件打点：`begin`→`lesson_began`、`send`→`student_message`、`media/done`→播放进度、`stop`→完成落库 | |
| `apps/server.py` | 端点 `GET /api/session/health`（**平台探活，缺失会让平台两处 Ready 变 false**）、`/api/session/demo-flag`、`/api/session/courses`、`/api/session/lesson` | 前端按 learning_context 渲染，不依赖本系统学生账号 |
| `apps/server.py` | 前端挂载在 **`/app`** 而非 `/`（`next.config.mjs` 的 `basePath="/app"` + Caddy 把 `/app*` 转发到 8000） | 改成挂 `/` 会让全部资源 404 |
| `orchestrator/agent.py` | `load_plan`：平台计划优先（`course_adapter.load_plan_for_session`）；`validate_plan` 给平台计划豁免本地 `stages/` 目录校验 | |
| `orchestrator/agent.py` | `load_context`：`tutor_context` 优先、`segment_by_id` 优先、平台态跳过阶段文件、平台计划直接取 `segments[].knowledge_point_ids` | |
| `orchestrator/agent.py` | `build_question_queue`（平台题库优先 + 保留上游 `lesson_id` 分支）、`_segment_detail`（平台段落优先）、`llm_polish`（平台事实边界约束）、`_hint`（平台提示优先，`state` 经 `_recap_scaffold` 透传） | |
| `frontend/src/components/StudentApp.js` | 双入口：带 `launch_token` 则跳过登录门走平台深链；否则走上游登录/选课门控。平台态才注册播放器适配器 | |
| `frontend/src/legacy/api.js` | `startSession` 注入 `launch_token`；`normalizeTurn` 透出 `sessionId`；新增 `fetchSessionCourses(sessionId)`→`/api/session/courses` | |
| `frontend/src/legacy/stage-class.js` | 播放器 mount context 同时传 `lesson`（平台适配器读 `playerUrl`）与 `video`（独立态默认播放器） | |

## 环境变量

| 变量 | 作用 |
|---|---|
| `STUDENT_SERVICE_KEY` | 与平台共享的服务密钥（launch token 签名+authorize 校验）；未配置时令牌入口 fail-closed |
| `AGENT_PORT=8000` | 本机端口（平台默认 STUDENT_URL/PUBLIC_URL 指向 8000） |

## 上游更新迁移步骤

> ⚠️ 早期版本这里写的是「冲突只可能在 `apps/server.py` 两处挂钩」，**已过时**。
> 上游重写 `apps/server.py`（909→1188 行，新增老师上传课时、学生自注册选课、课程码）
> 与 `orchestrator/agent.py`（新增 `load_lesson`/`save_lesson`/`validate_plan` 等六个函数），
> 挂钩面已横跨 Python 与前端。以本文档上面的「业务文件挂钩」表为准。

1. **覆盖上游**：`git archive origin/student-agent | tar -x -C student_agent/`
   （两条历史无共同祖先，不能用 `git merge`）。`tar` 只写归档里有的文件，
   所以 main 独有的适配层文件天然保留。
   然后补做上游**有意删除**的文件（tar 不会删）：`rules/*/SKILL.md`、
   `stages/recap_discussion/{questions,rubric}.md`、`frontend/src/legacy/theme.js`。
2. **恢复会被上游改错的配置**：`frontend/next.config.mjs` 的 `basePath="/app"`、
   `requirements.txt` 的 `psycopg[binary]`（上游没有，`persistence.py` 依赖）、
   `.gitignore` 里 `apps/static/app/` 的忽略规则、`apps/start.py` banner 的 `/app`。
3. **重放挂钩**：按上面的表逐条重放（server.py / agent.py / 前端三处）。
4. **验证**：`python apps/smoke_test.py stages`（独立态）
   + 令牌挂钩三用例（伪造→401、合法→通过签名校验、篡改→401）
   + `scripts/verify_student_entry.py`（平台态，平台 venv；**需课程已发布**）
   + 重建前端 `cd frontend && npm ci && npm run build` 并同步 `out/` 到 `apps/static/app/`。
5. 注意：用 `python apps/server.py` 直接跑**没有** `sys.path` 里的项目根，
   `from apps.integration import ...` 会 `ModuleNotFoundError`。
   必须走 `apps/start.py`（进程内 uvicorn）或平台启动器。

## 已知边界

- 会话仍存 `runtime/sessions/*.json`（统一 student schema 属后续阶段）；platform 上下文已随会话持久化，重启可恢复。
- 学生前端 `/app` 已消费 `launch_token`（`StudentApp.js` 深链 + `api.js` 注入），平台入口跳过登录门。
- 平台完整快乐路径（学生在平台上点已发布课程 → 进课堂）需要**课程已发布**：
  `teacher.mentra_knowledge_packages` / `teacher.mentra_classrooms` 为空时，
  `POST /courses/{id}/student-workspace` 返回 `409 课程尚未发布`。这是数据状态，不是代码故障。
- 课程内容加载仍是本地单课计划 + 平台已发布计划两条路；本地计划用于独立态与老师上传课时。

## Player integration (portable adapter)

- `frontend/src/integration/platform-player-adapter.js`: complete-file adapter; embeds the platform-provided `playerUrl`, validates `postMessage` source/origin, and maps playback completion to `onEnded`.
- `frontend/src/components/StudentApp.js`: two import lines plus one `registerVideoPlayer(...)` hook.
- `frontend/src/legacy/stage-class.js`: passes the already-loaded lesson into the player mount context.
- `apps/server.py`: `/api/session/lesson` exposes only the trusted `classroomId` and `playerUrl` stored in the verified launch context.
- Upstream migration: copy the adapter, replay the two frontend hooks and the two response fields, rebuild the static frontend, then run the integration adapter tests.

## Course-grounded tutor prompts (portable adapter)

- `apps/integration/prompt_context.py`: complete-file adapter; converts the verified published plan into bounded LLM facts, deterministic recap/deep-inquiry questions, dynamic hints and knowledge-point titles.
- `apps/integration/course_adapter.py`: small hook; bind each generated segment to matching published knowledge points, with a single-segment fallback to all published points.
- `orchestrator/agent.py`: small hooks only: pass the plan into question construction, prefer platform segments over local demo files, inject bounded published facts into `llm_polish`, and use dynamic course hints.
- `tests/test_integration_adapters.py`: verifies segment/knowledge binding, published narration in the prompt, course-grounded questions and absence of the legacy operating-system course.
- Upstream migration: copy `prompt_context.py`, replay the adapter/orchestrator hooks, run `python -m py_compile ...` and `python -m unittest discover -s tests -p "test_integration_*.py"`, then perform one explicitly authorized real-model prompt check.
