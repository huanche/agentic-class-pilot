# Agentic Class Pilot Constitution

## Core Principles

### I. 服务边界自治 (Service Boundary Autonomy) — NON-NEGOTIABLE

- `platform/`、`teacher_agent/`、`student_agent/` 三个服务 MUST 保持代码边界。
- platform MUST 独占身份认证、角色权限、课程关系与统一入口;各 Agent 负责自身业务逻辑。
- 跨服务交互 MUST 通过可信服务接口(服务密钥)与共享 PostgreSQL/MinIO 完成;
  禁止 import 其他服务的内部代码或直接读写其他服务私有的表结构。

**Rationale**: 三服务独立构建与部署;边界一旦破坏,发布节奏互相耦合、回滚范围不可控。

### II. 统一入口与可信会话 (Unified Entry & Trusted Session)

- 日常访问 MUST 从统一入口 `http://localhost:8088`(生产为对应域名)进入。
- Agent 内部端口(3200 教师 / 8000 学生)仅限开发调试;绕过入口的访问 MUST NOT
  被当作缺陷依据或写进文档作为用法。
- 嵌入式播放器等适配层路径 MUST 携带所需查询参数(如 `?embedded=player`);
  新增跳转或嵌入路径时同样适用。

**Rationale**: 直连 Agent 端口会缺少平台会话与可信启动参数,曾产生难以复现的
"刷新掉登录"类缺陷;参数丢失曾导致嵌入播放器行为异常。

### III. 密钥与凭证不入库 (Secrets Never Committed) — NON-NEGOTIABLE

- `.env`、`LOCAL-ACCESS.txt`、真实 API Key 等敏感信息 MUST 保持 Git 忽略,
  禁止以任何形式提交到仓库。
- 新增配置项 MUST 同步维护 `.env.example` 类模板并注明用途。

**Rationale**: 仓库为多人协作且镜像对外发布,泄漏不可逆。

### IV. 仓库即唯一事实源 (Repository as Single Source of Truth)

- 在生产服务器容器内实施的热修 MUST 尽快以等价改动回填仓库并走正常评审;
  禁止修复长期只存在于容器里。
- 部署与修复脚本 MUST 纳入仓库管理(如 `teacher_agent/scripts/deploy-*.sh`);
- 生产服务器布局或部署流程变更后,MUST 同步更新相关文档。

**Rationale**: 容器热修未回填曾导致环境漂移与重复排查;脚本散落本机则发布不可复现。

### V. 先验证后发布 (Verify Before Ship)

- 功能改动 MUST 先在本地全栈环境以 8088 入口端到端验证,再进入发布流程。
- 前端 `src` 变更后 MUST 重新执行对应构建(学生端 `构建前端.cmd`、教师端 pnpm build);
  禁止旧构建产物静默上线,构建指纹守卫失败 MUST 当作发布阻塞处理。

**Rationale**: 学生端曾因 serve 旧 `frontend/out` 产物出现"刷新后掉登录/回到加入课程页"
的线上缺陷;未经入口验证的改动无法覆盖会话与代理链路。

### VI. Git 流程与产物卫生 (Git Workflow & Artifact Hygiene)

- 功能 MUST 在特性分支(如 `lzm`)开发,阶段性并入 `main`,并入后回同步分支;
  合并前 MUST 先 `git fetch`(多人仓库,远端可能已有新提交)。
- 构建产物(tar 包、dist、构建日志等)MUST NOT 提交入库。
- `main` 的发布走 CI/CD(构建镜像 → Docker Hub → SSH 部署,含回滚);
  流程行为开关默认关闭,按需经 repo Variables 开启。

**Rationale**: tar 产物误传曾污染仓库根目录;多人环境下不 fetch 即合并会产生
无谓冲突;CI 开关默认关闭以防误发布。

## 技术栈与环境约束

- **技术栈**:
  - 平台前端 React + TypeScript + Vite;平台后端 FastAPI + SQLModel + Alembic。
  - 教师端 Next.js + React + TypeScript,pnpm 管理。
  - 学生端 FastAPI + Python + LangGraph,静态前端产物。
- **基础设施**: PostgreSQL 16、MinIO、Mailpit、Caddy、Docker Compose。
- **环境要求**: Windows 10/11 + PowerShell 5.1+、Docker Desktop、Python 3.10+、
  uv、Node.js 22.19+、pnpm 10+。
- **端口约定**: 8088 统一入口;8080 平台后端与前端;3200 教师 Agent;
  8000 学生 Agent;59001 MinIO;58025 Mailpit。
- 仓库路径含空格与中文,shell 命令中的路径 MUST 加引号。
- 生成的计划、盘点、迁移方案等文档 MUST 放在对应子项目的 `docs/` 目录,
  命名用英文 kebab-case;禁止写入用户级 Claude 目录。

## 开发与发布工作流

- 功能开发遵循 Spec Kit 流程:`/speckit-specify` → `/speckit-clarify` →
  `/speckit-plan` → `/speckit-tasks` → `/speckit-implement`,必要时以
  `/speckit-analyze` 做跨工件一致性检查。
- 提交信息使用 conventional 前缀(`feat:`/`fix:`/`docs:` 等,可带 scope),
  描述正文可中文。
- 发布路径:教师镜像本地构建后推送再用脚本部署;`main` push 可触发 CI/CD
  自动部署,异常时优先使用既有回滚机制,而非在生产上叠加热修(若热修,
  回填义务见原则 IV)。
- 每次发布前核对:前端产物为最新构建、验证已在 8088 完成、无构建产物混入提交。

## Governance

- 本宪法是项目最高治理文档;与其他文档或个人习惯冲突时,以本宪法为准。
- 修订 MUST 通过 PR 完成:说明修订内容与影响,按语义化版本递增
  `CONSTITUTION_VERSION`,涉及原则删除或重定义时附迁移说明。
- 版本策略:MAJOR = 原则删除或向后不兼容的重定义;MINOR = 新增原则/章节或
  实质性扩展;PATCH = 澄清与措辞修正。
- 合规审查:PR 评审 MUST 核对涉改原则;引入的复杂度 MUST 能以对应原则解释。
- 运行时开发指引见 `.specify/memory/` 与各子项目 `CLAUDE.md`;宪法与指引冲突
  时以宪法为准。

**Version**: 1.0.0 | **Ratified**: 2026-10-09 | **Last Amended**: 2026-10-09
