# PLATFORM-INTEGRATION（学生 Agent 平台适配清单）

遵循与教师 Agent 相同的可平移性约定（见教师仓库 PLATFORM-INTEGRATION.md）：
平台语义只放独立模块，业务文件只留最小挂钩，逐条登记，上游更新时按清单重放。

## 独立模块（整文件平移）

| 文件 | 职责 |
|---|---|
| `apps/platform_adapter.py` | launch token 校验（HMAC-SHA256，密钥 `STUDENT_SERVICE_KEY`，与平台 `student_bridge.py` 同格式）：签名/有效期/必填字段校验；`launch_context()` 输出归一化上下文（userId/courseId/classroomId/publicationId/version） |
| `scripts/verify_student_entry.py` | 可信入口验收脚本（发布链路搭建 + 8 项检查），用平台 venv python 运行 |
| `frontend/src/platform/playerAdapter.js` | 播放器 iframe 适配器：嵌入教师端 `/teacher/classroom-player/{id}`（Caddy 剥前缀），监听 SCENE_COMPLETED / PLAYBACK_ENDED postMessage（校验 origin+classroomId，按 eventId 幂等），映射到学生 Agent 的 media_done。教师端需配置 `NEXT_PUBLIC_SAAS_HOST_ORIGIN`（事件目标）与 `ALLOWED_FRAME_ANCESTORS`（CSP 嵌入许可），均为构建期内联 |

## 业务文件挂钩

| 文件 | 挂钩 | 说明 |
|---|---|---|
| `apps/server.py` | `StartIn.launch_token` 字段；`/api/session/start` 开头 20 行：令牌验证→身份以令牌为准（调用方 `student_id` 被忽略）→ `state["platform"]` 持久化（含 publication version 固定） | 阶段 5+ 的会话/内容适配继续在此模块化扩展 |
| `apps/server.py` | `GET /api/session/health` | 平台 `studentAgentReady` 探活端点 |

## 环境变量

| 变量 | 作用 |
|---|---|
| `STUDENT_SERVICE_KEY` | 与平台共享的服务密钥（launch token 签名+authorize 校验）；未配置时令牌入口 fail-closed |
| `AGENT_PORT=8000` | 本机端口（平台默认 STUDENT_URL/PUBLIC_URL 指向 8000） |

## 上游更新迁移步骤

1. 合并上游；冲突只可能在 `apps/server.py` 两处挂钩。
2. 整文件平移独立模块。
3. 重放挂钩（start 的令牌分支 + health 端点）。
4. 验证：`python apps/smoke_test.py stages`（独立态）+ `scripts/verify_student_entry.py`（平台态，平台 venv）。

## 已知边界

- 会话仍存 `runtime/sessions/*.json`（统一 student schema 属后续阶段）；platform 上下文已随会话持久化，重启可恢复。
- 学生前端 `/app` 页尚未自动消费 `launch_token` 参数（当前令牌入口在 API 层闭环，前端接线随播放器/学生端界面阶段一起做）。
- 课程内容加载仍是本地单课计划；按 courseId/publication 加载已发布内容属下一阶段。

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
