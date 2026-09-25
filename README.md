# Agentic Class Pilot

Agentic Class Pilot 是一个面向教师和学生的 AI 教育平台原型。项目由统一平台、教师 Agent 和学生 Agent 三个相互独立的服务组成，通过可信身份、服务接口和统一 PostgreSQL 数据库协同工作。

当前版本支持统一登录与角色入口、教师课程建设与授课、学生选课与课堂学习、课程内容发布、课堂播放器、邮件验证以及对象存储等功能。

## 项目结构

```text
agentic class pilot/
├─ platform/        # 平台基座：登录注册、角色权限、课程关系、统一入口和反向代理
├─ teacher_agent/   # 教师 Agent：课程建设、课件生成、内容发布、授课与播放器
└─ student_agent/   # 学生 Agent：课程学习、课堂互动和学习状态
```

三个服务保持代码边界，平台负责身份与访问控制，各 Agent 负责自己的业务逻辑。开发环境使用同一套 PostgreSQL 和 MinIO 服务，并通过服务密钥完成后端之间的可信调用。

## 技术组成

- 平台前端：React、TypeScript、Vite
- 平台后端：FastAPI、SQLModel、Alembic
- 教师端：Next.js、React、TypeScript、pnpm
- 学生端：FastAPI、Python、LangGraph、静态前端
- 基础设施：PostgreSQL 16、MinIO、Mailpit、Caddy、Docker Compose

## 本机端口

| 地址 | 用途 |
| --- | --- |
| `http://localhost:8088` | 统一访问入口，日常使用此地址 |
| `http://127.0.0.1:8080` | 平台后端及平台前端 |
| `http://127.0.0.1:3200` | 教师 Agent 内部开发地址 |
| `http://127.0.0.1:8000` | 学生 Agent 内部开发地址 |
| `http://127.0.0.1:59001` | MinIO 管理界面 |
| `http://127.0.0.1:58025` | Mailpit 本地邮件界面 |

请从 `8088` 进入系统。直接访问 Agent 端口可能缺少平台会话或可信启动参数。

## 环境要求

- Windows 10/11 和 PowerShell 5.1 或更高版本
- Docker Desktop
- Python 3.10 或更高版本
- [uv](https://docs.astral.sh/uv/)
- Node.js 22.19 或更高版本
- pnpm 10 或更高版本

所有命令均假定当前目录为本仓库根目录。由于目录名包含空格，请在 PowerShell 中使用引号或先进入目标目录。

## 首次安装

### 1. 安装平台依赖并生成本机配置

```powershell
Set-Location ".\platform"
powershell -ExecutionPolicy Bypass -File ".\scripts\bootstrap-local.ps1"
```

脚本会安装平台依赖。若 `platform/.env` 不存在，还会生成本机密钥和管理员账号，并将本机登录信息写入 `platform/LOCAL-ACCESS.txt`。这些文件包含敏感信息，已被 Git 忽略。

### 2. 安装教师 Agent 依赖

```powershell
Set-Location "..\teacher_agent"
pnpm install --frozen-lockfile
Copy-Item ".env.example" ".env.local" -ErrorAction SilentlyContinue
```

按需编辑 `teacher_agent/.env.local`，配置大模型、图像生成、语音合成等提供方。不要提交真实 API Key。

### 3. 安装学生 Agent 依赖

```powershell
Set-Location "..\student_agent"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item ".env.local.example" ".env.local" -ErrorAction SilentlyContinue
```

如需启用学生 Agent 的大模型对话，在 `student_agent/.env.local` 中配置 `AGENT_LLM_BASE_URL`、`AGENT_LLM_API_KEY` 和 `AGENT_LLM_MODEL`。

## 启动项目

进入平台目录并运行统一启动脚本：

```powershell
Set-Location "..\platform"
powershell -ExecutionPolicy Bypass -File ".\scripts\start-local.ps1"
```

等待各服务完成编译后，打开：

```text
http://localhost:8088
```

启动脚本会完成以下工作：

1. 启动 PostgreSQL、MinIO、Mailpit 和 Caddy。
2. 执行平台数据库迁移。
3. 启动平台后端（8080）。
4. 启动教师 Agent（3200）。
5. 启动学生 Agent（8000）。

可使用以下命令检查服务：

```powershell
Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8080/api/v1/utils/health-check/"
Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:3200/api/health"
Invoke-WebRequest -UseBasicParsing "http://localhost:8088"
```

## 常见问题

### 教师工作平台返回 502

先检查教师端健康接口：

```powershell
Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:3200/api/health"
```

如果代码刚移动过目录，pnpm 链接或 Next.js 缓存可能仍指向旧路径。关闭教师端进程后，在 `teacher_agent` 中执行：

```powershell
Remove-Item ".next" -Recurse -Force -ErrorAction SilentlyContinue
pnpm install --frozen-lockfile
```

然后重新运行平台统一启动脚本。

### 端口已被占用

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8088,8080,3200,8000
```

不要重复启动同一个服务。确认已有服务来自本项目后，可直接继续使用。

### 登录信息在哪里

首次执行初始化后，本机管理员账号位于 `platform/LOCAL-ACCESS.txt`。该文件只供本地使用，不应上传。

## 数据与安全

- PostgreSQL 和 MinIO 数据保存在 Docker 命名卷中，移动源码目录不会自动迁移或删除这些数据。
- `platform/.env`、各 Agent 的 `.env.local`、`LOCAL-ACCESS.txt`、运行日志和会话数据均不得提交。
- 上传前建议执行 `git status --ignored`，确认没有真实密码、API Key、数据库导出或用户数据进入暂存区。
- 生产部署必须替换开发密钥，启用 HTTPS、数据库备份、日志与监控，并使用正式 SMTP 和受控的对象存储权限。

## 开发边界

- 平台负责统一身份、角色权限、课程访问关系、统一入口和服务编排。
- 教师 Agent 负责课程内容建设、课件与课堂发布、授课和播放器业务。
- 学生 Agent 只通过平台签发的可信上下文进入课程，不接受前端自行指定用户身份。
- 平台集成代码应放在独立适配模块中，业务文件只保留最小挂钩，便于后续同步教师或学生 Agent 的上游更新。

更详细的子项目说明参见：

- `docs/database-architecture.md`
- `docs/database-er-diagram.md`
- `platform/docs/integration-log.md`
- `teacher_agent/PLATFORM-INTEGRATION.md`
- `teacher_agent/README-zh.md`
- `student_agent/README.md`

## 开源说明

教师端基于 [THU-MAIC/OpenMAIC](https://github.com/THU-MAIC/OpenMAIC) 扩展。发布仓库前，请保留各上游项目的许可证与版权声明，并根据实际采用的依赖补充本仓库的许可证和第三方软件说明。
