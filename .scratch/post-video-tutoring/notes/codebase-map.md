# 代码地图：课后辅导对话系统实施参考

> 快照日期：2026-10-20，基线 origin/main@151affd。行号会漂移，以符号搜索为准。

## 总体结构

- `platform/`：平台基座，FastAPI 后端 + React 前端，PostgreSQL（alembic 迁移）
- `teacher_agent/`：教师端 Next.js（OpenMAIC 扩展），多 provider LLM 注册表
- `student_agent/`：学生端，FastAPI + LangGraph 编排 + 静态导出 Next.js 前端；内部端口 8000；统一入口 localhost:8088（Caddy），`/app*` 转发到 8000，前端 basePath=`/app`

## 学生端前端（student_agent/frontend/）

- 路由与分流：`src/legacy/app.js:100-137`（#、#/course/:cid、#/lesson/...、#/class/...、#/review/...、#/replay/...）；服务端回合应用 `applyServerTurn`（`app.js:405-437`）
- 阶段词汇表：`src/legacy/phases.js:16-35`（host_phase 状态机：uninitialized→intro→guided_learning→recap_discussion→deep_inquiry→class_discussion→ending）
- 讲解阶段视图（chat+video）：`src/legacy/stage-class.js`；`notifyVideoEnd`（`:186-208`）现有 20–30 秒"老师准备中"空窗文案（`:194-196`）——本工单要用辅导过渡态替换
- 结束页：`src/legacy/stage-done.js:30-33`（"去课后"按钮，占位）
- 课后页：`src/legacy/view-review.js`（学情报告 + "再看一遍"→#/replay，`:209-211`）
- API 封装：`src/legacy/api.js`（统一消息端点 `:132-135`，轮询 `:168-170`，平台态课程/课时 `:56-75`，视频地址平台态返回 null `:77-86`）
- 播放器适配（唯一活路径）：`src/integration/platform-player-adapter.js`（`?embedded=player` `:22`，postMessage origin 校验 `:42`，SCENE_COMPLETED/PLAYBACK_ENDED 处理 `:45-53`）
- 死代码勿动：`src/platform/playerAdapter.js`
- 平台入口判定：`src/components/StudentApp.js:32-65`（launch_token 深链 vs 独立登录）

## 学生端后端（student_agent/）

- `apps/server.py`：`ACTIONS`（`ended` 后仅 export，`:62-66`）；`SESSIONS` 内存 dict（`:71`）+ `runtime/sessions/*.json` 落盘恢复（`:112-137`、`:437-453`）；`media/done` 事件步进（`:1235-1280`，幂等写 playback_progress）；平台态课程/课时聚合（`:1557-1604`）；独立态学生账号（`:992-1100`）
- `orchestrator/agent.py`：LangGraph 11 节点 `build_graph`（`:2021-2057`）；`teach` 两层结构=确定性骨架决定教学动作 + LLM 润色（`:1193-1213`）；教学提示词（`:1094-1166`）；复述/探究判答（`:1484-1499`）；LLM 客户端 `llm_chat`（`:122-154`，OpenAI 兼容 /chat/completions，env `AGENT_LLM_BASE_URL/API_KEY/MODEL`）
- BYOK：平台态每会话首轮拉用户模型配置覆盖 env（`server.py:181-191` → `orchestrator/llm_override.py`）
- 持久化分层：`orchestrator/persistence.py`（demo 态 `runtime/integration/*.json` `:23-34`；课后报告写入 `:192-207`）
- 编排规范：`orchestrator/ORCHESTRATOR.md`

## 平台后端（platform/backend/）

- 学生桥：`app/api/routes/student_bridge.py`（launch_token 签发 `:48-60`；learning-context 版本化已发布上下文=知识点+材料摘录 `:352-400`；learning-progress `:592-621`）
- student schema 七表：`app/alembic/versions/final05_student_schema.py`（student_sessions、student_messages、learning_events、playback_progress、knowledge_mastery、task_submissions、after_class_reports）
- BYOK 模型配置：`user_model_config.py`

## 工作惯例（重要）

- 改学生端前端 src 后**必须重跑** `构建前端.cmd`（喂 `<NUL` 防交互挂起）；静态产物在 frontend/out
- 学生端 e2e：基址 `/app`，LLM 用确定性桩；构建脚本 quirks 见仓库脚本
- 平台前端 pnpm 10 的审批绕法见已有脚本/CI
- 提交信息沿用仓库风格（英文 conventional commits，如 `feat(student): ...`）
- 所有给人读的工单/评论内容用简体中文；`Status:` 等机器记号保持英文
- 多人仓库：合并前必 fetch；tar/构建产物不提交
