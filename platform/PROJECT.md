# Learning Helper — LMS + AI 智能体系统

基于 [Full Stack FastAPI Template](https://github.com/fastapi/full-stack-fastapi-template) 的 LMS，内置两个 LangGraph 智能体：**学生章节问答**（流式对话，带跨会话短期记忆）与**教师教学大纲助手**。

> 历史注记：2026-09-17 之前本系统还包含「AI 课件生成」主干（OpenMAIC 代理 + 课堂快照 + MinIO 媒体 + 站内回放），已整体移除；完整实现可在 git 历史（`main` 分支）中找回。

## 架构

```
┌─────────────────────┐      ┌───────────────────────────┐      ┌────────────────┐
│  frontend/          │      │  backend/                 │      │  LLM API       │
│  React + Vite       │─────▶│  FastAPI (JWT 鉴权)       │─────▶│  (OpenAI 兼容,  │
│  http://localhost:5173     │  http://localhost:8001    │      │   如 DeepSeek)  │
└─────────────────────┘      │                           │      └────────────────┘
      ▲ SSE 流式问答          │  ├─ LangGraphAgent 学生问答│
      └──────────────────────│  ├─ OutlineAgent 教师大纲  │
                             │  └─ 模型工厂(重试/降级)    │
                             └────────────┬──────────────┘
                                          │
                                 ┌────────┴───────────┐
                                 │  PostgreSQL :5433  │
                                 │  业务表 + agent    │
                                 │  checkpoint 三表   │
                                 └────────────────────┘
```

- **登录/鉴权**：模板自带 JWT（OAuth2 password flow），所有接口由后端鉴权。
- **注册**：需邮箱验证码（`POST /users/send-verification-code`）。6 位验证码，10 分钟有效、60 秒重发冷却、每邮箱每天 10 次上限、试错 5 次作废；验证码加盐哈希存储，注册成功即消费。本地开发邮件进 Mailpit（http://localhost:8025），上线前配置真实 SMTP（`.env` 的 `SMTP_*`）。
- **角色**：注册时自选「学生/教师」（`User.role`）。教师建课、用大纲助手规划教学；学生用选课码加入课程、就章节内容与问答 agent 对话。
- **课程/章节**：`Course`（含 8 位 `enroll_code`）/ `Chapter` 模型；教师按 `owner_id` 隔离，学生通过 `Enrollment` 获得只读权限。
- **学习进度**：章节级打点（`ChapterProgress`），学生在章节上点「标记已学」，「我的课程」页显示进度条。
- **学生问答 Agent**（LangGraphAgent，`app/core/langgraph/graph.py`）：每 (用户, 章节) 一个会话（`ChatSession` 表），SSE 流式打字机输出；对话历史存 LangGraph checkpoint 三表（PostgreSQL），跨访问持久。系统提示词为中文助教模板（`app/core/prompts/system.md`），章节标题/说明作为上下文注入。
- **教师大纲 Agent**（OutlineAgent，`app/core/langgraph/outline.py`）：按课程上下文（Course + Chapter）给出教学大纲/周计划建议，带私有工具（如 `suggest_weekly_plan`），教师端面板流式交互。
- **模型工厂**（`app/services/llm/`）：OpenAI 兼容接口（配置项 `LLM_API_KEY`/`LLM_BASE_URL`/`LLM_MODEL`，见 `.env`）；tenacity 重试 + 循环降级 + 总超时预算，工具绑定在降级间保持。

## 启动步骤

### 0. 前置

- Docker Desktop（PostgreSQL、Mailpit）
- Python 3.14+ 与 uv；bun（前端用）
- 至少一个 OpenAI 兼容 LLM API Key（DeepSeek / Qwen 等）

### 1. 数据库与后端

```bash
docker compose up -d db mailpit    # PostgreSQL 在 localhost:5433
cd backend
uv sync
uv run alembic upgrade head        # 建表（checkpoint 三表由 agent 启动时自建）
uv run python app/initial_data.py  # 创建管理员（首次）
uv run uvicorn app.main:app --port 8001 --reload   # Windows 本机跑需带 --reload（事件循环兼容）
```

管理员账号见根目录 `.env`（`FIRST_SUPERUSER` / `FIRST_SUPERUSER_PASSWORD`）。API 文档：http://localhost:8001/docs

### 2. 前端

```bash
bun install          # 仓库根目录（workspace）
bun run dev          # = frontend vite dev server，http://localhost:5173
```

后端接口变更后重新生成客户端：

```bash
bash scripts/generate-client.sh
```

### 3. 使用流程

1. 浏览器打开 http://localhost:5173 ，用管理员账号登录。
2. 教师侧：「课程」→ 新建课程 → 进入课程 → 新建章节；「教学大纲」面板可与大纲助手对话。
3. 学生侧：用选课码加入课程 → 进入章节 → 「章节问答」流式提问，多轮上下文自动延续。

## 目录说明

| 路径 | 说明 |
|---|---|
| `backend/app/models.py` | User/Item（模板）+ Course/Chapter/Enrollment/ChatSession（LMS） |
| `backend/app/api/routes/courses.py` | 课程与章节 CRUD |
| `backend/app/api/routes/chat.py` | 问答会话 CRUD + chat/SSE/历史/清空端点 |
| `backend/app/api/routes/outline.py` | 教师大纲 agent 端点（teacher-gated） |
| `backend/app/core/langgraph/` | 两个 agent 的图编排、共享 checkpoint、消息工具、工具注册表 |
| `backend/app/services/llm/` | LLM 模型工厂（重试/降级/结构化输出） |
| `backend/app/core/prompts/` | 中文系统提示词模板（Markdown + 变量注入） |
| `frontend/src/components/Courses/` | AskPanel（流式问答）、OutlinePanel（大纲助手）等 |
| `frontend/src/lib/streamChat.ts` | SSE 流式消费（fetch + ReadableStream 逐帧解析） |
| `docs/langgraph-migration-plan.md` | agent 能力从 vendor 模板迁移的完整记录 |

## 已知取舍 / 后续迭代

- **长期记忆未做**：agent 记忆是 checkpoint 短期记忆（会话内多轮 + 跨访问）；mem0/向量库方案已明确排除（决策记录见 `docs/langgraph-migration-plan.md` 进度区）。
- **限流/指标/结构化日志**（vendor 模板第 5/6 步能力）推迟到对外部署前再评估。
- **工具注册表空置**（学生问答 agent）：机制就绪，等真实教学工具需求再接入。
- 旧 `POST /ask/chapters/{id}` 非流式问答路由保留作对照，待下线。
