# Agent 集成实施日志（agentedu-final）

## 教师产品入口收敛（2026-09-22）

- 平台新增 `/teacher` 教师门户，登录后按可信角色直接进入；学生仍进入原学习首页。
- 教师门户只提供“课程建设”和“授课管理”两个已有产品入口，不复制教师 Agent 的课程、Class 或学情页面。
- 教师侧边栏收敛为产品首页、课程建设、授课管理；管理员仍保留用户管理。
- 教师 Agent 顶层页面返回目标统一为平台 `/teacher`。
- 平台后端的课程、选课、身份和服务鉴权能力继续保留，页面精简不改变数据所有权。

本文件是三服务集成的唯一实施清单，每阶段记录：修改文件、数据库迁移、配置项、测试命令、测试结果、已知限制、回退方法。
阶段定义见任务书；原则：平台管身份/成员/入口，教师 Agent 管创课/备课/发布，学生 Agent 管会话/学习数据；三服务共享一个 PostgreSQL、各自 schema、最小权限。

## 目录与端口规划（本机调试）

| 服务 | 目录 | 端口 | 说明 |
|---|---|---|---|
| 平台基座 | `E:\LLM\code_project\ai_education_platform\platform` | 8080 | 正在运行（PID 会变），正式入口 `/api/*` |
| 旧版教师 Agent（仅参考/回退） | `E:\LLM\code_project\ai_education_platform\agent\SZU-AgentEduPlatform` | 3100 | 不再开发业务，保留回退 |
| 新版教师 Agent | `E:\LLM\code_project\ai_education_platform\agent\teacher_agent\SZU-AgentEduPlatform` | **3200**（阶段 1 起） | 正式入口 `/teacher/*` |
| 学生 Agent | `E:\LLM\code_project\ai_education_platform\agent\student_agent\SZU_Student_Agent` | 8000 | 正式入口 `/student/*` |
| PostgreSQL 16 | docker `agentedu-final-database-1` | 55432 | 库 `education`（public/teacher/student schema）+ `app_test`；超级用户角色 `platform` |
| Mailpit | docker `agentedu-final-mail-1` | 51025/58025 | 本地邮件 |

## 环境事实（2026-09-22 记录）

- 工具链：node v24.13.0、pnpm 11.10.0、python 3.10.11（系统）、uv 0.12.15、platform/.venv（项目虚拟环境）。
- Docker 在运行：`agentedu-final-database-1`（postgres:16, 127.0.0.1:55432）、`agentedu-final-mail-1`；另有旧 demo 的 minio/valkey/pgvector(5432) 容器在跑，与本集成无关，不要误用 5432。
- 8080 已被平台占用（正在运行的服务）；8000/3100/3200 空闲。
- 两个教师仓库的 `.gitignore` 均已忽略 `/.runtime/` 与 `.env*`。

---

# 阶段 0：建立基线（2026-09-22）✅

## 完成内容

1. 四个目录的 Git 状态盘点（含旧版参考仓库的未提交对接代码完整清单）。
2. 阅读 `agent/SZU-AgentEduPlatform/.runtime/integration-progress.md`（上一次集成验收记录）与 `verify-teacher-candidate.py`（3101 候选验收脚本，阶段 1 将改造为 3200 版）。
3. 对旧版未提交的对接代码计算 SHA256 指纹，存 `agent/SZU-AgentEduPlatform/.runtime/integration-code-fingerprints-phase0.txt`，用于后续校验是否被意外改动。
4. platform 原本**不是 git 仓库**（集成无版本控制、无法回退）→ 补 `.gitignore`（LOCAL-ACCESS.txt、local-db-init/01-roles.sql、.venv/，均含本机密钥/生成物）→ `git init -b main` → 基线提交 `ae4155f`（359 文件，已核实无 .env/密码/构建产物入库）。
5. 跑三个项目现有测试，记录原始失败（见下）。
6. 新版教师仓库建立 `.runtime/baseline/` 存档两份基线日志（vitest 全量日志、tsc 错误清单）。

## Git 状态盘点

### platform（阶段 0 前）
- 非 git 仓库。处置：init + 基线提交 `ae4155f`，工作树干净。

### 新版教师 Agent `agent/teacher_agent/SZU-AgentEduPlatform`
- HEAD `d55d9b3`（3 commits）。未提交改动：
  - `M packages/@openmaic/renderer/fonts.css`、`M packages/@openmaic/renderer/src/snapshot/katex-fonts-embed.ts`（上游字体嵌入产物）
  - `M pnpm-lock.yaml`（integration-progress.md 记载：补 integration-contract 缺的 typescript 条目）
  - `?? packages/integration-contract/node_modules/`（**未被忽略**，阶段 1 处理）
  - `?? tests/course-space/class-publication.test.ts`（**Class 发布隔离测试，未跟踪**，阶段 1 提交）

### 学生 Agent `agent/student_agent/SZU_Student_Agent`
- HEAD `08c7433`（1 commit）。仅 `M runtime/DIALOGUE-LOG.md`（运行期产物）。

### 旧版教师 Agent `agent/SZU-AgentEduPlatform`（参考，未改动）
- HEAD `d9c486e`。**全部平台对接代码处于未提交状态**（阶段 2 移植的蓝本）：
  - 未跟踪：`lib/server/platform-auth.ts`、`lib/server/platform-resource-sync.ts`、`.pnpm-store/`、`backups/`
  - 修改（12）：`middleware.ts`、`next.config.ts`、`app/api/course-space/route.ts`、`app/api/course-space/[courseId]/materials/route.ts`、`app/course-space/[courseId]/page.tsx`、`app/course-space/page.tsx`、`components/course-space/course-center.tsx`、`components/course-space/course-workspace-explorer.tsx`、`lib/course-space/types.ts`、`lib/server/course-material-parser.ts`、`lib/server/course-space-database.ts`、`lib/server/course-space-storage.ts`（另有两个 renderer 字体文件，与新版相同的上游产物）
- 指纹（SHA256 前 16 位，完整值见 `.runtime/integration-code-fingerprints-phase0.txt`）：
  `platform-auth.ts 882562573eed8e48`、`platform-resource-sync.ts b00fbadecbaa7c32`、`middleware.ts c8ae4b2757925d7d`、`course-space/route.ts 778502ad7859a0ba`、`course-space-storage.ts cc4f556cde46e906`、`course-space-database.ts c912b0a931feef38`、`types.ts bfaa8f5aa7758e59`、`next.config.ts 4b8fb5c6d8a333ac` 等。
- 风险与建议：这是对接实现的唯一副本，建议项目所有者尽快提交；本次集成不代为提交（任务书要求仅记录、不覆盖他人工作）。

## 基线测试结果（原始失败记录）

### 平台基座（pytest，对 app_test 库）
- 命令：`platform/.venv/Scripts/python.exe platform/scripts/check_backend.py`（内部：alembic upgrade head + pytest tests -q，DATABASE_URL 重写为 app_test）
- 结果：**158 passed, 2 warnings**（0 失败）。迁移链在 app_test 上干净通过。

### 新版教师 Agent（vitest + tsc）
- 命令：`pnpm -C <dir> test`；`pnpm -C <dir> exec tsc --noEmit`
- vitest 结果：**20 test files failed | 458 passed | 3 skipped（481 文件）；86 tests failed | 4875 passed | 61 skipped（5022）**（第一次运行 23 文件/97 用例失败，数量略有波动）。全量日志：`.runtime/baseline/vitest-baseline.log`。
- **失败全部位于上游 OpenMAIC 功能区**（chat/pi 路由、CI 元测试、文档导入、视频导出、quiz 运行时等 20 个文件，清单见日志），**course-space / Class 发布 / 存储相关测试全部通过**（`class-publication.test.ts` 2 通过、`migration.test.ts` 11 通过、`server-course-space.test.ts` 3 通过）。
- tsc 结果：**7 个错误，全部在 `tests/course-space/migration.test.ts`**（引用过时类型：`'published'` 状态、`'quiz'` 产物类型、`fileName` 字段等；运行时该文件测试实际通过，属类型层过期）。清单：`.runtime/baseline/tsc-baseline.log`。
- 结论：这些失败/类型错误均为**存量问题**，与本次集成无关；阶段 1 第 5 条要求修复 TS 错误（该文件在待修范围），上游 OpenMAIC 模块的 86 个失败不在集成关键路径，记录在案、不阻塞（如需修复另立任务）。

### 学生 Agent（HTTP 冒烟）
- 命令：`python apps/start.py --no-browser --port 8000` 后 `python apps/smoke_test.py stages`
- 结果：**通过**。完整流程：begin → 视频播完(media_done) → 复述问答（判星）→ next → 深层探究 → 下课总结。无 LLM 配置时走 `[模板]` 确定性降级（设计内行为）。
- 说明：该测试向 `runtime/` 写入会话数据（项目自身行为，`runtime/` 已被 git 忽略）。

## 已知限制与风险

1. 旧版未提交对接代码有丢失风险（已记指纹，建议所有者提交）。
2. 新版 `packages/integration-contract/node_modules/` 未被 gitignore（阶段 1 处理）；`class-publication.test.ts` 未跟踪（阶段 1 提交）。
3. 新版 86 个存量 vitest 失败在上游模块，集成验收时以 course-space 相关测试 + 新增集成测试为准。
4. 8080 平台服务当前在运行旧拓扑；阶段 1-2 的新版教师 Agent 用 3200 独立运行，不触碰 8080/3100。
5. 上次集成记录（integration-progress.md）中未完成的项：播放器加载持久化课堂未验证（编译期 OOM）、可信身份/归属/DB schema/可重试登记未接入候选——即本次阶段 1-4 的工作内容。

## 修改的文件（阶段 0）

| 文件 | 作用 |
|---|---|
| `platform/.gitignore`（追加 3 行） | 忽略 LOCAL-ACCESS.txt、local-db-init/01-roles.sql（含生成密码）、.venv/，防密钥入库 |
| `platform/docs/integration-log.md`（新建） | 本清单 |
| `agent/SZU-AgentEduPlatform/.runtime/integration-code-fingerprints-phase0.txt`（新建，gitignored） | 旧版对接代码指纹 |
| `agent/teacher_agent/SZU-AgentEduPlatform/.runtime/baseline/*`（新建，gitignored） | vitest/tsc 基线日志存档 |

环境变量：无新增。数据库迁移：无。

## 回退方法（阶段 0）

- platform：`git -C platform reset --hard ae4155f^`（退到 init 前不可能，init 前无版本）；实际上阶段 0 只新增了忽略规则和文档，`git checkout ae4155f -- .gitignore && git -C platform rm docs/integration-log.md` 即可完全撤销；最彻底删除 `.git/` 目录回到无版本状态。
- 其余三个仓库：阶段 0 未做任何修改（学生 Agent 的 DIALOGUE-LOG.md 为运行期产物）。

---

# 阶段 1：单独跑通新版教师 Agent（3200）✅（2026-09-22）

## 完成内容

1. `lib/server/classroom-storage.ts` 支持 `CLASSROOMS_DATA_DIR` / `CLASSROOM_JOBS_DATA_DIR` 环境变量（镜像既有 `COURSE_SPACES_DATA_DIR` 模式），实现课堂数据目录隔离。
2. 新版 `.env.local`：从旧版提取最后一次出现的非空 provider 配置（DEEPSEEK_*、OPENAI_*、DEFAULT_MODEL），剔除旧文件中的空值重复条目与断行脏数据；`PERSISTENCE_DEV_TOKEN`、`NEXT_PUBLIC_PERSISTENCE_TOKEN`、`STUDENT_AGENT_API_KEY` 全部新生成随机值（旧值为乱码占位符）。**不复制** `PLATFORM_API_BASE_URL`/`TEACHER_AGENT_SERVICE_KEY`（孤儿链路，阶段 2 另配）。**不设置** `NEXT_PUBLIC_PERSISTENCE`（原因见"发现"第 3 条）。
3. `scripts/dev-3200.ps1`：仿旧版 3101 启动脚本，清除 DB/平台变量 + 三个数据目录全部指向 `.runtime/data-3200/` + `NODE_OPTIONS=--max-old-space-size=8192`（防上次验收遇到的 dev 编译 OOM）。
4. 修复 `tests/course-space/migration.test.ts` 全部 9 处类型错误（7 处基线 + 2 处被掩盖），夹具对齐当前领域类型；`pnpm exec tsc --noEmit` 退出码 0。
5. **修复存量 bug**：挂载型课件产物首次激活必 500。根因：`classrooms/attach` 生成 `attached_*` 合成 jobId 且无 job 记录，产物 PATCH 路由无条件 `updateCourseJob` → `throw 'Job not found'`。修复：存储层新增 `updateCourseJobIfPresent`（产物链路专用；生成任务运行器保持严格语义），产物路由两处调用改用之。新增路由级回归测试 4 例。
6. `scripts/acceptance/verify_teacher_3200.py`：改造自旧版 verify-teacher-candidate.py，扩展材料上传/激活、真实持久化课堂、挂载/悬空拒绝/幂等、草稿隔离断言。
7. 浏览器级验证（IAB）：`/classroom-player/{classroomId}` 真实渲染通过。

## 验证结果（命令与输出）

- 验收脚本（对 3200，最终配置下复跑）：**15 项全 PASS**——health+capabilities（classroomPlayer 稳定入口）、创课、发布前 Class 通道关闭（404/409）、材料上传、发布门禁、产物激活幂等（CLS-A-*）+ 撤回拒绝、材料草稿隔离+激活（CLS-M-*）、课堂持久化+可取回、挂载（review 态不泄露/幂等/悬空 404）、挂载产物激活、4 个页面壳（`/`、`/teacher-workspace?workspace=`、`/classroom-player/{真实id}`、缺失 id）。
- 浏览器渲染：播放器页加载持久化课堂，场景标题/时间轴/播放控件/AI 教师等四角色全部渲染，无报错。截图已存档。
- `pnpm exec tsc --noEmit`：exit 0。
- course-space 测试：10 文件 60 例 + 新增 4 例全部通过。
- 全量 vitest 回归：见下方"已知限制"第 1 条（与基线持平，无新增失败）。
- `/api/health` capabilities：`imageGeneration: true`、`tts: false`、`courseDatabase: false`（JSON 模式，符合阶段 1 预期）。

## 发现（重要）

1. **挂载产物激活 500 是存量 bug**（非本次引入）：上一轮 3101 验收没走到"挂载后激活"所以没暴露。已修复+回归测试锁住。
2. **上次"播放器未验证通过"的真正根因有两个**：(a) dev 编译 OOM——本次用 `NODE_OPTIONS=--max-old-space-size=8192` 规避，4.1s 就绪；(b) 播放器客户端持久化层在 `NEXT_PUBLIC_PERSISTENCE=1` 时强依赖服务端 `/api/persistence` → 要求 `DATABASE_URL`，而隔离启动脚本会清掉它 → 页面报 `server persistence not configured`。
3. **服务端持久化（`NEXT_PUBLIC_PERSISTENCE=1`）与任务书"DDL 只能迁移管理"冲突**：@openmaic/storage 的服务端持久化在运行期自动建表（document/runtime/asset 存储）。阶段 1 决定关闭该开关（用浏览器本地 IndexedDB 持久化，上游默认模式）；阶段 3 统一数据库时必须为这些表设计迁移归属（或保持浏览器本地持久化并明确边界）后再启用。
4. 空合成场景上 Play/Auto-play 可激活但时间轴不推进（无旁白/动作/TTS 的退化夹具），真实播放链路留待阶段 4/6 用真实生成课件验证——符合任务书第 7 条降级说明。

## 修改的文件与提交

新版教师仓库两个提交：
- `6e4e42a` fix: activate attached courseware artifacts without a job record
  - `app/api/course-space/[courseId]/artifacts/[artifactId]/route.ts`（改用 updateCourseJobIfPresent）
  - `lib/server/course-space-storage.ts`（新增 updateCourseJobIfPresent）
  - `tests/course-space/artifact-activation.test.ts`（新增回归测试 4 例）
- `fa36e91` chore: phase-1 standalone acceptance tooling and type fixes
  - `lib/server/classroom-storage.ts`（数据目录环境变量）
  - `scripts/dev-3200.ps1`、`scripts/acceptance/verify_teacher_3200.py`（启动+验收工具）
  - `tests/course-space/migration.test.ts`（类型修复）
  - `tests/course-space/class-publication.test.ts`（上轮遗留未跟踪，纳入）
  - `pnpm-lock.yaml`（上轮补的 integration-contract typescript 条目，纳入）
  - `.gitignore`（node_modules 覆盖子包）
- 未动的既有修改：`packages/@openmaic/renderer/fonts.css`、`katex-fonts-embed.ts`（上游字体产物）、测试快照 eol 噪声——非本次工作，保持原样。

## 新增/修改的环境变量（.env.local，gitignored）

DEEPSEEK_API_KEY/BASE_URL/MODELS、OPENAI_API_KEY/BASE_URL/MODELS、DEFAULT_MODEL（自旧版净化复制）；PERSISTENCE_ALLOW_INSECURE_DEV_AUTH=true、PERSISTENCE_DEV_TOKEN、NEXT_PUBLIC_PERSISTENCE_TOKEN、STUDENT_AGENT_API_KEY（全新随机值）。运行时（dev-3200.ps1 设置）：COURSE_SPACES_DATA_DIR、CLASSROOMS_DATA_DIR、CLASSROOM_JOBS_DATA_DIR、NEXT_PUBLIC_SAAS_HOST_ORIGIN、ALLOWED_FRAME_ANCESTORS、NODE_OPTIONS；并清除 DATABASE_URL/COURSE_DATABASE_URL/PLATFORM_AUTH_ENABLED/ACCESS_CODE。

数据库迁移：无（阶段 1 为 JSON 文件模式，数据在 `.runtime/data-3200/`）。

## 已知限制

1. 全量 vitest 存量失败与基线持平（上游 OpenMAIC 模块，course-space 零失败）；详见 `.runtime/baseline/vitest-phase1.log` 与基线日志对比。
2. 无 TTS provider：课件生成的语音走降级策略；真实播放推进待阶段 4/6。
3. 服务端持久化关闭（浏览器本地 IndexedDB），见"发现"第 3 条。
4. `data/usage`（用量统计）目录无环境变量隔离，仍写仓库根 `data/usage`（非正式业务数据，接受）。

## 手工验收步骤

1. 启动：`powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev-3200.ps1`（当前会话已在运行，可直接访问）。
2. 打开 http://127.0.0.1:3200/（首页双入口）、http://127.0.0.1:3200/teacher-workspace（工作台）。
3. 跑验收：`python scripts/acceptance/verify_teacher_3200.py`（应 15 项 ALL PASS）。
4. 浏览器打开脚本输出末尾打印的 `/classroom-player/{classroomId}` 地址，确认渲染。
5. `pnpm exec tsc --noEmit` 应无输出退出 0。

## 回退方法

- 代码回退：`git -C <新版仓库> revert 6e4e42a fa36e91`（或 reset 到 d55d9b3）。
- 运行态回退：停掉 3200 进程即可（TaskStop / 关闭窗口）；`.runtime/data-3200/` 为一次性验收数据，可整目录删除。
- `.env.local` 删除即回到无配置状态。

---

# 阶段 2：移植可信身份适配 ✅（2026-09-22）

## 完成内容

教师侧（独立模块移植，未动业务主体）：
1. `lib/server/platform-auth.ts`（新文件，自旧版移植+强化）：每请求回调 `POST {PLATFORM_AUTH_URL}/api/v1/internal/teacher/authorize`；转发 `agentedu_session` cookie；剥离外部伪造的 `x-platform-user-id/-admin/-delegated`；服务调用（`X-Platform-Service-Key`+`X-Platform-Subject`）委托鉴权并打内部标记 `x-platform-delegated`；平台不可达 fail-closed 503；**path 带上 query string**（平台侧据此解析 `GET /api/classroom?id=` 的课堂归属）；异常记录日志（不打印 cookie）。
2. `middleware.ts`：`PLATFORM_AUTH_ENABLED=true` 时全量委托 platformMiddleware（`/api/health` 白名单）。
3. `app/api/course-space/route.ts`：平台模式下教师身份只来自 `x-platform-user-id`（query/body 的 teacherId 无效，DEFAULT_TEACHER_ID 只在独立模式用）；建课后向平台幂等登记（有界重试 3 次/250ms，4xx 快速失败）；`body.id` 幂等再登记；**委托调用跳过回调登记**（平台侧本来就在写链接，避免 JSON 模式下必然失败的双写）。
4. `lib/server/course-space-storage.ts`：平台模式 courseId 用 UUID v4（独立模式保持 nanoid）。
5. 未移植：旧版孤儿 `materials/sync` 链路（任务书明确不移植）；"DB 优先"存储语义（阶段 3）；`TEACHER_BASE_PATH`（部署阶段）。

平台侧（teacher_bridge.py，保持对旧版 3100 的兼容）：
1. 写请求 Origin 白名单改为 `FRONTEND_HOST + TEACHER_ALLOWED_ORIGINS`（新增配置项，本机 .env 配了 3100/3200）。
2. classroom 作用域解析：`GET /api/classroom?id=`（query）、`/api/classroom-media/{classroomId}/...`、页面 `/classroom-player/{id}` 与旧 `/classroom/{id}` → `teacher.mentra_classrooms` 反查 course_id → 归属校验（404/403）；未挂课的独立课堂按无归属处理（走旧规则）。
3. 教师可用 API 前缀扩充：`course-space/classes/classroom/classroom-media`（均带作用域校验）；其余无归属 API 维持仅管理员（不变）。
4. `/api/classes/{courseId}` 按课程归属鉴权（新版 Class 视图）。

## 验证结果

- 教师端单测：`tests/server/platform-auth.test.ts` **9/9**（401/403/307 重定向/503 fail-closed/伪造头剥离/委托标记/cookie+path+origin 传递/服务头条件化）。
- 平台端测试：`tests/api/routes/test_teacher_bridge.py` **12/12**（服务密钥/匿名/学生角色/写源白名单/课程归属互斥/课堂 API-query 作用域/媒体路径作用域/播放器页面作用域/legacy 管理员规则/委托跳过源检查）；全量平台套件 **170 passed**（158 基线 + 12 新增）。
- tsc：exit 0。**目标范围测试（本阶段涉及面）69/69 通过**：9 项身份单测 + 60 项 course-space 套件。
- **扩展测试诚实说明**：教师端全仓 vitest 仍存在量失败（上游 OpenMAIC 模块，见基线记录），失败集合为阶段 0 基线子集、无新增；其中 `tests/server/classroom-generation-retry.test.ts` 仍有 1–2 项失败（超时类 flaky，非本阶段引入）。**不得表述为"全仓测试全部通过"**。
- 端到端（`scripts/acceptance/verify_phase2_identity.py`，真实双服务）**10/10 PASS**：双服务健康；真实账号（超管 API 建教师/学生，登录拿 `agentedu_session`）；匿名 API 401 / 页面 307 到平台登录；学生角色 403；教师列自己课程；建课 UUID + 登记降级 502（JSON 模式文档化行为）；query teacherId 伪造无效；委托调用精确 UUID + 幂等 + 不重复；错误服务密钥按匿名 401；未知课程作用域路径 404。

## 关键发现与决策

1. **pydantic-settings 忽略空字符串环境变量**：`SMTP_USER=` 空覆盖会穿透回 .env 真值。本机验证因此改用超管 API 直接开号（邮箱注册流程已由平台单测覆盖）。
2. **`emails` 库的 SMTP AUTH 路径对 Mailpit 不兼容**（带 user/password 发送返回 SMTPResponse None，无认证 250 正常）——本地邮件验证链路受此限制，属上游库问题，未改平台邮件代码。
3. **TaskStop 会留下 python 孤儿进程**：Windows 下杀 bash 壳不杀子进程，导致 8080 被旧实例占用、新实例静默失败。处置：重启前显式 taskkill 监听端口的 PID（已记入手工验收步骤）。
4. 课程登记成功闭环依赖共享库中 `teacher.mentra_courses` 有行（平台登记端点会反查归属）——**阶段 3 接入统一库后自然打通**，本阶段以 502 + 明确文案降级，且因登记幂等 + body.id 重试路径，阶段 3 无需改代码即可恢复。
5. 播放器页面在平台鉴权下走"课堂归属"校验；JSON 模式下课堂不在共享库 → 404（旧浏览器标签页轮询可观察到），符合预期。

## 修改的文件与提交

- 新版教师仓库 `e06c18b`：`lib/server/platform-auth.ts`（新）、`middleware.ts`、`app/api/course-space/route.ts`、`lib/server/course-space-storage.ts`、`lib/course-space/types.ts`、`lib/server/api-response.ts`（+SERVICE_UNAVAILABLE 错误码）、`tests/server/platform-auth.test.ts`（新）、`scripts/dev-3200-platform.ps1`（新，平台鉴权启动器）、`scripts/acceptance/verify_phase2_identity.py`（新）。
- 平台仓库 `abdbe98`：`backend/app/core/config.py`（TEACHER_ALLOWED_ORIGINS）、`backend/app/api/routes/teacher_bridge.py`（作用域/白名单/前缀）、`backend/tests/api/routes/test_teacher_bridge.py`（新）、`scripts/pytest_route.py`（新，定向测试入口）。
- platform/.env（本机，gitignored）：追加 `TEACHER_ALLOWED_ORIGINS=http://localhost:3100,http://localhost:3200,http://127.0.0.1:3200`。

## 新增环境变量

教师侧（dev-3200-platform.ps1 设置）：`PLATFORM_AUTH_ENABLED=true`、`PLATFORM_AUTH_URL=http://127.0.0.1:8080`、`PLATFORM_PUBLIC_URL=http://localhost:8080`、`PLATFORM_SERVICE_KEY`（运行时从 platform/.env 读）。平台侧：`TEACHER_ALLOWED_ORIGINS`。数据库迁移：无。

## 可平移性约定（贯穿后续所有阶段）

按项目所有者要求（2026-09-22）：对教师 Agent / 学生 Agent 的修改必须方便上游更新后直接迁移。
执行标准：**平台语义只放独立模块，业务文件只留最小挂钩，逐条登记**。

- 教师侧落地为 `lib/server/platform-auth.ts` + `lib/server/platform-course-bridge.ts` 两个独立模块，
  `app/api/course-space/route.ts` 已重构为薄挂钩形态（平台语义全部来自 bridge），存储层 id 生成收进
  `generateCourseId()`。挂钩清单与迁移步骤见教师仓库 `PLATFORM-INTEGRATION.md`。
- 学生 Agent（阶段 5 起）遵循同一约定：适配层独立成模块（如 `platform_adapter`），业务文件最小挂钩并登记。
- 本阶段重构后复验：tsc 0、69/69 单测、身份验收 10/10 全过。

## 已知限制

1. 课程登记成功闭环、跨教师归属 403（真实课程在共享库）待阶段 3；本阶段验证为 502/404 降级路径。
2. 教师端 UI 仍会在 query 里带 teacherId（服务端忽略之；UI 线程化留待阶段 7 统一处理）。
3. 本地 Mailpit 邮件链路受 emails 库 AUTH 兼容性限制（见发现 2）；不影响生产 SMTP。
4. `data/usage` 目录仍未隔离（沿用阶段 1 结论）。
5. 全量教师端 vitest 回归见 `.runtime/baseline/vitest-phase2.log`（与基线对比结论见报告）。

## 手工验收步骤

1. 确认数据库容器与 Mailpit 在跑；启动平台后端：`cd platform/backend && .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080`（需要 Mailpit 时加 `SMTP_HOST=127.0.0.1 SMTP_PORT=51025 SMTP_SSL=false SMTP_TLS=false SMTP_USER=localdev SMTP_PASSWORD=localdev`）。
2. 启动教师端（平台鉴权态）：`powershell -File scripts/dev-3200-platform.ps1`。
3. `python scripts/acceptance/verify_phase2_identity.py` → 10 项 ALL PASS。
4. 浏览器未登录打开 http://127.0.0.1:3200/course-space → 应跳平台登录页。
5. `pnpm exec vitest run tests/server/platform-auth.test.ts` 与平台 `python scripts/pytest_route.py tests/api/routes/test_teacher_bridge.py` 应全绿。

## 回退方法

- 教师侧：`git revert e06c18b`；或把启动器换回 `scripts/dev-3200.ps1`（不带平台变量）即回到阶段 1 独立态。
- 平台侧：`git revert abdbe98`（.env 的 TEACHER_ALLOWED_ORIGINS 一行删除即可）。
- 运行态：停 3200/8080 进程（先 taskkill 监听端口的孤儿 PID）。

---

# 阶段 2 运行入口切换（收尾，2026-09-22）✅

平台正式入口从旧版 3100 切换到新版教师端 3200（数据仍在 JSON 模式，统一库属阶段 3）。

1. **.env**：`TEACHER_URL=http://127.0.0.1:3200`（服务间调用）、`TEACHER_PUBLIC_URL=http://localhost:3200`（浏览器侧，此前缺省走代码默认 3100，本机 .env 原本未显式配置，已补）。
2. **teacher_bridge.py**：`open_teacher_workspace` 返回统一入口 `f"{TEACHER_PUBLIC_URL}/teacher-workspace?workspace={external_id}"`（原 `/course-space/{id}`）。
3. **前端去硬编码**：`frontend/src/routes/_layout/index.tsx` 与 `courses.index.tsx` 的 `http://localhost:3100/course-space` 全部移除，课程中心入口改为 `platform/status` 返回的 `teacherUrl` 拼接（未就绪时按钮禁用）；单课程入口继续走桥接接口返回的 url。前端已重新 `vite build`。
4. **验证**：
   - 后端实际读取 3200 配置：`GET /api/v1/platform/status` → `teacherUrl=http://localhost:3200`、`teacherReady=true`（探活 3200 成功）。
   - 桥接：`POST /courses/{id}/teacher-workspace` → `http://localhost:3200/teacher-workspace?workspace={uuid}`。
   - 浏览器全流程：登录平台 → 工作台出现课程卡片与 3200 课程中心链接 → 点击"进入教师工作区" → **落在 3200 `/teacher-workspace?workspace={courseId}` 且新版工作台完整渲染**（标题"教师课程工作区 v1.1"、委托开出的课程可见）。此流程同时打通了平台反向委托开课：桥接带服务密钥调 3200、委托建课（免回写登记）、写 `teacher_course_link`、返回新入口。
   - 切换后身份验证复跑：**10/10 PASS**（匿名 401/页面重定向、学生 403、伪造 teacherId 无效、跨教师路径拒绝等不变）。
5. **一次性验证数据**（可留可删）：教师账号 `browser-walkthrough-041b17@example.com`、平台课程"入口切换验证课程"（id 667042f9-4152-45d9-a806-26760093c0de，已在 3200 JSON 数据目录有对应工作区）。历次身份验证产生的 `phase2-*` 账号同理。
6. **回退**：`.env` 两行改回 3100 并重启平台即回旧拓扑；前端入口逻辑与版本无关（跟随配置），无需回退代码。`git revert` 本收尾提交可回退 bridge URL 形态与前端改动。

## 本机访问兼容修复（localhost 双栈监听，2026-09-22）

**问题**：教师端 `--hostname 127.0.0.1` 只监听 IPv4；Windows 把 `localhost` 同时解析为 `::1` 和 `127.0.0.1`（浏览器通常先试 `::1`），导致部分浏览器访问 `localhost:3200` 直接拒绝连接（实测 `[::1]:3200` 连接失败、`127.0.0.1:3200` 成功）。

**修复**：两个启动器（`dev-3200.ps1` / `dev-3200-platform.ps1`）的监听改为 `--hostname ::`。Node 的 `::` 绑定是双栈 socket——同一进程同时挂 `0.0.0.0:3200` 与 `[::]:3200`，IPv4-mapped 与 IPv6 请求都接受。`TEACHER_PUBLIC_URL` 保持 `http://localhost:3200` 不变（改成 127.0.0.1 会因 Cookie 主机不同丢失 `agentedu_session`）。注意：`::` 监听全部接口（与旧版 3100 仅回环不同），本机开发可接受——每个请求仍过平台鉴权；Windows 防火墙可能弹一次放行提示。

**验证**（重启 3200 后）：
- 监听：netstat 显示同一 PID 挂 `0.0.0.0:3200` + `[::]:3200`。
- 三地址健康检查全 200：`http://127.0.0.1:3200/api/health`、`http://[::1]:3200/api/health`、`http://localhost:3200/api/health`。
- 平台侧不变：`platform/status` → `teacherUrl=http://localhost:3200`、`teacherReady=true`（服务间仍走 `TEACHER_URL=127.0.0.1:3200`）。
- 浏览器：清理残留旧标签后重走流程——平台登录态保持 → "进入教师课程中心"链接 = `http://localhost:3200/course-space` → 课程卡片"进入教师工作区"落在 3200；桥接接口实测返回 `http://localhost:3200/teacher-workspace?workspace={courseId}`（页面加载后 SPA 会把地址规范化为 `/course-space/{id}`，同一页面组件的内部路由）。**全程地址无 3100**。

# 教师产品入口统一（2026-09-22）✅

教师产品入口全部收敛进 8080 平台侧边栏；平台与教师端之间不使用 iframe、不复制页面。

## 平台侧改动

1. **侧边栏**（`components/Sidebar/AppSidebar.tsx` + `Main.tsx`）：教师导航固定为 工作台 / 课程建设 / 授课管理 / 学生管理 / 学习数据，超管追加 用户管理；学生导航不变（工作台/我的课程/加入课程，零教师项泄漏）。`Item` 扩展 `external`（普通 `a` 标签 + 绝对 URL）与 `badge`（外部项带"教师工作区"标记与外链图标）；内部项继续走 RouterLink。课程建设 = `{teacherUrl}/course-space`、授课管理 = `{teacherUrl}/classes`，`teacherUrl` 一律来自 `GET /api/v1/platform/status`（共享 hook `frontend/src/hooks/usePlatformStatus.ts`，index/courses 页同步整合），**无任何硬编码 3200**；teacherUrl 未就绪时外部项暂不显示。
2. **/students**（`routes/_layout/students.tsx`）：按课程展示成员名单（姓名/邮箱/章节进度/加入时间，来自成员接口真实数据），保留跳转课程详情管理。
3. **/learning-data**（`routes/_layout/learning-data.tsx` 新增）：学生 Agent 未接入（`studentAgentReady=false`）时显示明确空状态说明；仅展示平台已有真实数据（各课程学生章节完成进度条），**无模拟统计**。
4. 前端已 `vite build`（含 routeTree 再生成）。

## 教师侧改动（按可平移约定）

1. 新增独立导航适配模块 `lib/integration/platform-links.ts`：平台地址只从 `NEXT_PUBLIC_SAAS_HOST_ORIGIN` 读取（本机 http://localhost:8080；上线同域 `/teacher` 反代时为站点 origin；生产为构建期内联，改值需重建）。
2. `components/course-space/course-center.tsx` 与 `app/classes/page.tsx` 的总览返回按钮统一 `platformHomeUrl()` 返回平台 8080；**课程内部页面导航保持教师端内部路由不变**。

## 验证（全部实测通过）

- 类型检查：平台前端 `tsc -p tsconfig.build.json` 0 错误（vite build 含 routeTree 再生成）；教师端 `tsc --noEmit` 0 错误。
- 平台套件 **170 passed**（含权限测试）；教师端 course-space+server 套件 284/285，仅 `classroom-generation-retry.test.ts` 1 项已知上游 flaky 失败（非本次引入，与阶段 2 记录一致）。
- 浏览器五项：①登录→课程建设→3200→返回管理平台 ②登录→授课管理→3200/classes（"授课 Class"渲染）→返回管理平台 ③学生账号侧边栏零教师项 ④登出后访问 3200/course-space 重定向回 8080/login ⑤刷新后身份保持。另：/students 与 /learning-data（空状态+真实进度）教师视角渲染正常。

## 一次性数据

`nav-student-13ca22@example.com`（学生，验证导航隔离用）。回退：`git revert` 两仓库本次提交即可；教师端返回按钮回退后恢复站内路由。

# 阶段 3 / 基础闭环修复（2026-09-22）✅

修复"无权访问该资源"（数据源分裂）并建立学生 Agent 可信入口。两个独立提交：Part A 教师存储统一（教师仓 `839f83f` / 平台仓 `b7b81fd`），Part B 学生可信入口（见下方提交号）。

## Part A：教师存储统一（修复课程无权访问）

- **对账结论**：public.course 6 门；`667042f9`（平台已登记）与 2345@example.com 的两门课（`64ae8a24`/`8215ad2e`）仅存在于 JSON → authorize 查 `teacher.mentra_courses` 404 → 中间件统一显示"无权访问"。验收夹具（local-teacher×5、phase2-*/临时账号×8）明确排除在正式库外。
- **DDL 归属**：平台迁移 `final02` 创建 teacher schema 16 张核心 `mentra_*` 表并授权 teacher 角色 DML；会话 6 张 `mentra_teacher_agent_*` 表仍由上游 `ensureAgentSessionSchema` 幂等自建（教师自有 schema，与旧版 3100 拓扑一致，已在移植文档登记）。
- **教师端存储**：`COURSE_STORAGE_MODE=json|postgres`（默认 json；postgres 无 URL 启动即失败）；`COURSE_DATABASE_SCHEMA=teacher`（search_path 隔离 + 运行期跳过核心 DDL）；course-space/classroom 存储 18 处门控使 DB 成为唯一事实源（postgres 模式无 JSON 回退）；课程列表/创建存储故障 → 503。
- **数据迁移**：`scripts/migrate_teacher_courses_to_db.py` 幂等迁入 3 门正式课程并补平台登记（include=3 exclude=13，剔除规则见脚本）。
- **错误码**：401 未登录 / 403 无权访问该课程（属于其他教师）/ 404 课程不存在或尚未同步 / 409 归属冲突（登记端点）/ 503 平台身份服务或数据库暂不可用（中间件透传平台具体文案，>=5xx 映射 503）。
- **验证**：自己的迁移课 200（DB 出数）、跨教师 403、未知 404、匿名 401、DB 列表不含夹具；平台套件 170 passed（清库后）。
- **排障记录**：app_test 曾因测试夹具自建极简表（无 NOT NULL 列）与迁移冲突 + 夹具 setup 中途失败毒化会话事务 → 迁移失败/全量级联。处置：夹具改依赖迁移表 + 启动自清理；重建 app_test 后全绿。教训已固化到 pytest_route（先跑 alembic）。

## Part B：学生 Agent 可信入口

- **平台侧**：`STUDENT_URL/STUDENT_PUBLIC_URL/STUDENT_SERVICE_KEY`（.env，密钥随机生成）；`POST /api/v1/internal/student/authorize`（服务密钥 + launch_token/会话 cookie + 选课复检）；`POST /api/v1/courses/{courseId}/student-workspace`（选课 + 已发布 + 已激活课堂 → 短期 HMAC launch_token + 学生端入口 URL + 播放器地址；教师 403 / 未选课 403 / 未发布 409）；`platform/status` 返回 studentAgentReady/studentUrl。
- **学生端**：独立适配模块 `apps/platform_adapter.py`（令牌校验 + 上下文）；`/api/session/start` 支持 launch_token（身份以令牌为准，调用方 student_id 忽略；`state.platform` 持久化并固定 publication version）；`/api/session/health` 探活。学生 Agent 移植清单 `PLATFORM-INTEGRATION.md` 已建立。
- **/student 产品页**：学生登录分流直达（教师 → /teacher 不变）；按已选课程展示真实发布状态（已发布=进入学习 / 未发布=等待教师发布 / 学生服务离线=暂不可用）；"进入学习"只调 student-workspace 跳转（前端不拼 8000 地址）；学生侧边栏=学生首页/我的课程/加入课程，零教师项。
- **验证**：验收脚本 8/8（正式发布链路、status、状态区分、403/409/403 门控、launch 签发含播放器地址、篡改/垃圾令牌 401、身份权威+版本固定、双学生会话隔离）；浏览器：学生登录落 /student、侧边栏正确；平台套件 **175 passed**（+5 学生桥测试）。

## 已知限制

1. 学生前端 `/app` 页尚未自动消费 launch_token 参数（API 层闭环，前端接线随播放器阶段）。
2. 学生会话仍在 runtime JSON（student schema 属下一阶段）；platform 上下文已随会话持久化。
3. 学生 Agent 按 courseId 加载已发布内容（转换器）属下一阶段；当前仍本地单课计划。

## 一次性数据

`b-student-*`、`probe-*`、`p3-check-*` 验证账号；`667042f9` 课程已正式发布（含 p3-stage 课堂与产物）——这些是真实测试态数据，可保留演示。回退：`git revert` 两仓库的 Part A/B 提交；数据回退需手工清理 mentra 行（迁移脚本幂等可重放）。

# 阶段 3：统一数据库——待执行
# 阶段 4：Class 与播放器授权——待执行
# 阶段 5：学生 Agent 适配与 student schema——待执行
# 阶段 6：播放器事件契约——待执行
# 阶段 7：完善平台界面——待执行
# 阶段 8：端到端验证——待执行

## 旧课程 ID 解析统一修复（2026-09-24）✅

导入"现代交换原理"后暴露的系统性问题：teacher schema 里旧课程用 nanoid 作主键，
而平台桥接端点（authorize 学生播放、enrollment 选课码、members 名单）的路径参数
声明为 uuid.UUID → 旧课程所有平台交互 422/503/403。

**修复**（`1dcf8d0`）：共享 `resolve_platform_course_id()`——UUID 直通、nanoid 查
`teacher_course_link` 映射；三个端点统一使用。实测：members 返回 7 名真实选课学生，
教师端班级详情页"学生与学习状态"显示真实名单（教师端桥接 `platform-course-members.ts`
为并行开发已有，本次打通平台侧）。

同批修复：网关补教师端原生页面路径路由（/classes/*、/classroom*、/prepare*、/review*、
/generation-preview*）——教师端内部 router.push 用无前缀路径，之前落入平台 SPA
fallback 显示 404 页（`1359629`）。

**待办**：智谱 API Key 过期（学生端 AI 对话与教师端实时生成受影响，课件回放不受影响）；
教师仓库并行改动未提交；app_test 库待同步 final03/04/05。
