# 中文架构与接口资产地图

> 盘点基线：`decouple-implementation` 分支，2026-10-29。本文是源码静态盘点与关键链路人工核对的结果，不代表运行环境实际启用了可选 API 模式，也不代表端到端测试已经通过。目标是降低一个模块改动时其他模块被迫跟改的概率，保留现有功能、权限和故障语义。

## 怎么读这张地图

- **提供方**：对数据和业务规则负责的服务。浏览器页面调用同一服务的 API 属于端内调用；跨平台、教师、学生服务的调用才是重点边界。
- **目前怎么访问**：`接口`表示 HTTP；`直查`表示调用方读写其他服务拥有的表；`双路可选`表示有新接口但默认仍走旧路径。不能把“接口已定义”误读为“生产已切换”。
- **测试状态**：`有针对性测试`只说明找到了对应测试；`待联调`表示未在本次盘点中运行三服务真实 HTTP 流程。静态扫描不能证明鉴权、延迟、故障恢复或完整覆盖。
- 路径以当前源码为准。字段、认证、响应语义看 [`contracts/README.md`](../contracts/README.md) 和对应 YAML；数据库表看 [`database-architecture.md`](database-architecture.md)。本页不复制另一份字段定义。

## 自动盘点范围与可复现命令

在仓库根目录运行以下只读命令；扫描排除依赖和生成代码后，再人工核对实际入口、配置开关、测试断言。计数是**源码声明数**，不是对外可访问端点数，也不是覆盖率。

```powershell
rg -n '^@router\.(get|post|put|patch|delete)|^@app\.(get|post|put|patch|delete)' platform/backend/app/api/routes student_agent/backend -g '*.py'
rg --files teacher_agent/app/api -g 'route.ts'
rg -n '^export (async )?function (GET|POST|PUT|PATCH|DELETE|HEAD)' teacher_agent/app/api -g 'route.ts'
rg -n 'httpx\.|urllib.request|fetch\(|PLATFORM_AUTH_URL|TEACHER_URL|STUDENT_URL' platform/backend/app/api platform/backend/app/services teacher_agent/lib/server student_agent/backend student_agent/agent -g '*.py' -g '*.ts' -g '!**/generated/**'
rg -n 'teacher\.|student\.|COURSE_DATABASE_SCHEMA|STUDENT_DATABASE_URL' platform/backend/app/api platform/backend/app/services teacher_agent/lib/server student_agent/backend student_agent/agent -g '*.py' -g '*.ts' -g '!**/tests/**'
rg --files platform/backend/tests teacher_agent/tests student_agent/backend/tests -g 'test_*.py' -g '*.test.ts' -g '*.test.tsx'
```

本次初筛：平台路由目录与学生后端共 **92** 条 Python 方法装饰器；教师端 **93** 个 `app/api/**/route.ts` 文件、**111** 个以标准 `export function` 形式声明的方法。平台路由由 [`platform/backend/app/api/main.py`](../platform/backend/app/api/main.py) 汇总，学生路由由 [`student_agent/backend/main.py`](../student_agent/backend/main.py) 汇总。测试文件初筛为平台 **29** 个 `test_*.py`、学生后端 **12** 个 `test_*.py`、教师端 **564** 个 `*.test.ts(x)`；这些数字包含端内业务测试，不能当作接口覆盖率。动态路由、间接构造的 URL、前端及第三方模型/媒体调用需要按业务链进一步核对。

## 业务功能与跨模块资产

| 业务功能 | 提供方／数据归属 | 调用方 | 目前怎么访问 | 测试状态与下一步验证 |
| --- | --- | --- | --- | --- |
| 登录、用户、角色、选课 | 平台；`public` 用户、课程、选课表 | 平台页面；教师和学生服务的授权流程 | 平台 `login`、`users`、`courses`、`enrollments` 路由；服务间通过内部授权 API | 平台有登录、课程、选课及权限测试；三服务会话过期和角色变化仍需联调 |
| 教师端每次请求的身份、课程所有权判断 | 平台负责用户/选课，教师端负责教师课程事实 | 教师端中间件调用平台 | 教师端 `POST /api/v1/internal/teacher/authorize`；平台处理器仍直查 `teacher.mentra_courses`、工件、课堂和任务表；这是**鉴权关键耦合** | [`test_teacher_bridge.py`](../platform/backend/tests/api/routes/test_teacher_bridge.py)、[`platform-auth.test.ts`](../teacher_agent/tests/server/platform-auth.test.ts)；必须验证撤销发布、换教师、学生越权，不能只测 200 |
| 教师创建课程并在平台登记 | 教师端拥有课程草稿；平台拥有管理课程 ID、选课记录和映射 | 教师端→平台；平台→教师端 | 教师端调用 `/internal/teacher/courses`，平台核对时直查 `teacher.mentra_courses`；平台教师工作区可用 `TEACHER_COURSE_PROVISION_MODE=api` 调教师 `POST /api/course-space`，默认 `legacy` | 教师课程接入及平台桥接有测试；需验证重复登记、创建一半失败、旧课程别名 |
| 教师课程建设、资料、课件生成 | 教师端；`teacher` schema 和媒体存储 | 教师页面、教师端内部调用 | 主要是教师端 `app/api/course-space/**`、`generate/**`、`classroom/**` 的端内 API；模型、语音、图像另连外部提供方 | 教师端有大量端内测试；完整生成耗时和第三方失败不由接口契约测试证明 |
| 发布、撤销及“当前可见”判定 | 教师端；教师课程、工件、知识包 | 平台、学生学习入口 | 教师拥有 `GET /api/internal/platform/courses/{courseId}/publication`；平台 `TEACHER_PUBLICATION_READ_MODE=legacy/shadow/api`，默认直查教师表 | [`test_teacher_publication_client.py`](../platform/backend/tests/unit/test_teacher_publication_client.py)、[`platform-publication-api.test.ts`](../teacher_agent/tests/course-space/platform-publication-api.test.ts)；待对照发布/撤销/旧数据的真实 HTTP 结果 |
| 最近已发布课堂 ID | 教师端；课堂及工件 | 平台学生工作区 | 教师拥有 `GET /api/internal/platform/courses/{courseId}/latest-classroom`；平台 `TEACHER_CLASSROOM_READ_MODE=legacy/shadow/api`，默认直查教师表 | [`test_teacher_classroom_client.py`](../platform/backend/tests/unit/test_teacher_classroom_client.py)、[`platform-latest-classroom.test.ts`](../teacher_agent/tests/course-space/platform-latest-classroom.test.ts)；待三服务影子对比、延迟和教师服务故障演练 |
| 学生启动学习与学习上下文 | 平台负责签发令牌、选课资格与组装；教师端拥有发布内容；学生端消费上下文 | 学生端→平台 | 学生端调用 `POST /api/v1/internal/student/learning-context`；平台在 [`student_bridge.py`](../platform/backend/app/api/routes/student_bridge.py) 直查教师课程、工件、课堂、资料解析、知识图谱等表并组装内容 | [`test_learning_context.py`](../platform/backend/tests/api/routes/test_learning_context.py)、[`test_student_lesson_context.py`](../platform/backend/tests/api/routes/test_student_lesson_context.py)、学生 [`test_platform_lesson_contract.py`](../student_agent/backend/tests/test_platform_lesson_contract.py)；**最高优先级对照**：选课、下架、空课时、旧课程 ID、权限、响应大小与耗时 |
| 学生查看已发布视频／资料 | 教师端拥有媒体和发布状态；平台拥有选课资格 | 学生浏览器→教师端；教师端→平台授权 | 学生播放器、媒体、资料 URL 指向教师端；平台授权处理器直查教师表判断发布可见，并查平台选课 | 平台教师桥接、教师发布生命周期测试；待真实浏览器验证 URL、资源撤销后禁止读取、跨课程越权 |
| 课时知识准备登记 | 学生端拥有 `student.published_lesson_knowledge`；教师发布触发、平台核实 | 教师端→平台→学生端 | 平台 `STUDENT_KNOWLEDGE_ENQUEUE_MODE=api` 可调学生内部 API，默认直接 `INSERT student` 表；平台核实发布状态又直查教师表 | [`test_student_knowledge_client.py`](../platform/backend/tests/unit/test_student_knowledge_client.py)、学生 `test_internal_platform_knowledge_db.py`；需验证重复触发幂等、失败恢复和无双写 |
| 学生会话、播放进度、掌握度 | 学生端；`student` schema | 学生页面／学生后端；平台学情页 | 学生端直接读写自有表；平台 `STUDENT_ANALYTICS_READ_MODE=api` 可调学生内部学情 API，默认仍直查 `student.student_sessions`、`knowledge_mastery`、`learning_events` | 学生数据库写入及平台学情客户端有测试；待真实课程大样本、分页/限制、权限和延迟验证 |
| 教师授课管理中的学情与进度 | 学生端拥有学习事件；教师端拥有授课管理视图；平台拥有选课名单 | 学生端→平台→教师端，教师页面→平台 | 学生端上报 `/internal/student/learning-progress`；平台从学生表与教师表算进度，可选两侧 analytics API（默认 `legacy`），再 `PUT /api/classes/{courseId}/students` 推教师端 | [`test_student_analytics_client.py`](../platform/backend/tests/unit/test_student_analytics_client.py)、学生 `test_internal_platform_analytics_db.py`；需测教师服务故障时学生学习不中断、重试/补偿及数据一致性 |
| 旧学生会话恢复课堂画面 | 教师端拥有课堂场景 | 学生端旧会话恢复逻辑 | [`student_agent/agent/persistence.py`](../student_agent/agent/persistence.py) 的 `classroom_scenes` 直接读 `teacher.mentra_classrooms`；仅旧上下文缺少课时资料时使用 | 学生重放测试存在；需用真实旧会话样本确认调用频率与停用条件，之后再设计最小替代读取 |
| 模型配置 | 平台拥有用户密钥与配置 | 教师端、学生端 | 平台 `/internal/user/{user_id}/model-config`；教师端 `platform-user-model-config.ts`、学生端平台客户端消费 | 契约已声明；需核对密钥脱敏、用户撤权、缓存和实际运行日志 |

## 接口来源与调用方：已核对的跨服务入口

| 方向 | 提供方源码 | 调用方源码 | 契约来源／现状 |
| --- | --- | --- | --- |
| 教师→平台 | [`teacher_bridge.py`](../platform/backend/app/api/routes/teacher_bridge.py)、[`user_model_config.py`](../platform/backend/app/api/routes/user_model_config.py) | `teacher_agent/lib/server/platform-auth.ts`、`platform-course-bridge.ts`、`platform-enrollment.ts`、`platform-course-members.ts`、`platform-user-model-config.ts`、`course-resource-publication.ts` | [`internal-teacher-api.yaml`](../contracts/internal-teacher-api.yaml)；7 条路径（其中模型配置与学生契约共享）；业务适配仍要核对每个调用点 |
| 学生→平台 | [`student_bridge.py`](../platform/backend/app/api/routes/student_bridge.py)、`user_model_config.py` | [`student_agent/backend/main.py`](../student_agent/backend/main.py)、[`agent/platform_client.py`](../student_agent/agent/platform_client.py) | [`internal-student-api.yaml`](../contracts/internal-student-api.yaml)；4 条路径；`STUDENT_PLATFORM_CLIENT_MODE` 默认 `legacy`，仅学习上下文有生成客户端可选路径 |
| 平台→教师 | `teacher_agent/app/api/internal/platform/**`，以及健康、建课、授课状态 API | `platform/backend/app/services/teacher_*_client.py`、`teacher_bridge.py`、`student_bridge.py` | [`teacher-service-api.yaml`](../contracts/teacher-service-api.yaml)；6 条路径；发布、课堂、建课、统计开关默认旧路径 |
| 平台→学生 | [`student_agent/backend/internal_platform.py`](../student_agent/backend/internal_platform.py) | `platform/backend/app/services/student_*_client.py` | [`student-service-api.yaml`](../contracts/student-service-api.yaml)；3 条路径；知识登记、学情开关默认旧路径 |
| 学生→教师 | 教师 `app/api/student-agent/v1/**`、`app/api/course-data/v1/**` | 当前学生后端源码未检出对应 HTTP 调用；学生浏览器仍使用教师播放器与媒体 URL | **提供方存在不等于实际被消费**。`student-agent/v1` 当前仅凭 Bearer 令牌的调用还会先经过教师端平台授权中间件，不能直接当作旧会话跨表读取的替代；其课程响应的资料、课时归属和课堂场景语义也与平台学习上下文不同。先确认调用和权限设计，再决定是否复用 |

## 数据库依赖与变更影响

当前三个服务可连接同一 PostgreSQL 实例，但数据所有权按 `public`（平台）、`teacher`（教师）、`student`（学生）划分。平台 ORM 在 [`models.py`](../platform/backend/app/models.py) 管理平台表；教师端在 [`course-space-database.ts`](../teacher_agent/lib/server/course-space-database.ts) 使用 `COURSE_DATABASE_URL` / `COURSE_DATABASE_SCHEMA`；学生端在 [`database.py`](../student_agent/agent/database.py) 使用 `STUDENT_DATABASE_URL`。平台 [`core/db.py`](../platform/backend/app/core/db.py) 使用 `DATABASE_URL`。同实例不必然造成业务耦合；**跨所有权读写及依赖他方 JSON 内部形状**才是当前主要变更风险。

| 依赖级别 | 具体位置 | 修改另一模块时可能波及什么 | 验证门槛 |
| --- | --- | --- | --- |
| 高：平台直查教师内容及发布字段 | `student_bridge.py` 的 `_published_package_payload`、`published_course_entries`、`_classroom_view`、`_published_lessons`、`_grounding_context`；`teacher_bridge.py` 鉴权 | 教师课程 JSON、发布标志、课堂场景或图谱结构变动可能破坏学生入口/鉴权 | 逐个固定语义、权限、旧数据样本；先影子对比再切流 |
| 高：平台直写学生知识表 | `student_bridge.py` 的 `ensure_published_knowledge_job`，默认旧路径 | 学生表/任务语义变动可能破坏发布后的知识准备 | 幂等、重复请求、失败回滚、无双写 |
| 中：平台直查学生学情表 | `student_bridge.py` 的 `course_learning_data`、`_course_learning_progress` | 学生会话/掌握度表变动可能破坏教师学情和同步 | 数据量、时间口径、权限、性能、故障返回 |
| 中：学生直查教师课堂表 | `agent/persistence.py` 的 `classroom_scenes` | 教师课堂表调整可能破坏旧会话恢复 | 确定旧会话占比和场景兼容要求 |
| 高：平台跨表鉴权 | `teacher_bridge.py` 的 `_authorize_teacher_request` | 无法简单撤销平台对 `teacher` schema 的读取权限 | 先设计无循环调用的授权判断，再在独立库收紧权限 |

## 可理解性与可观察性缺口

1. **覆盖关系**：静态扫描能找到路由和测试文件，不能自动证明每条跨服务业务路径有正向、越权、超时、撤销发布、旧数据测试。上述表格逐项标出待联调；后续把真实请求追踪与测试用例编号补到对应行。
2. **实际调用**：`legacy/shadow/api` 模式由运行配置决定，源码有接口不等于实际走接口。联调时应在隔离环境记录每条业务路径的模式、调用方向、状态码、耗时、失败数、影子差异数和回退结果；日志不得输出令牌、服务密钥、模型密钥或完整学习上下文。
3. **性能与可靠性**：直接 SQL 通常少一次网络跳转；HTTP API 让数据拥有方能够独立改内部表，但多一次序列化、网络及服务可用性依赖。比较 `p50/p95`、错误率、响应体大小、下架生效时间；不能只看单次成功或把 API 当作天然更快。
4. **下一次验证顺序**：先在独立测试库做最近课堂 `shadow` 和真实三端 HTTP 对比；再核对学习上下文的输出语义与权限；之后处理鉴权依赖和旧会话；最后以受限数据库角色证明平台不再需要跨 schema 权限。每次只切一个读取点，保留可回退模式。当前不具备撤销跨表权限或合并生产 `main` 的证据。

### 2026-10-29 最近课堂读取的隔离验证

在独立 `app_test` 数据库、独立平台端口 `18080` 和教师端口 `18088`，用合成教师、课程、课堂及已发布工件做真实 HTTP 调用。`legacy`、`shadow`、`api` 三种模式对“已发布”均返回同一课堂 ID；撤销工件发布及停用课程后均返回空。错误服务密钥请求被拒绝（401）；模拟教师端不可用时，`shadow` 仍返回旧结果，`api` 返回 503。合成数据已清理。验证脚本保存在忽略目录 `.runtime/classroom-http-probe.py`，只允许连接名为 `app_test` 的独立库。

单次请求的观测值：预热后的 API 请求约 53–106 ms，旧 SQL 查询约 4–61 ms；第一次 `shadow` 请求约 1.8 s，包含 Next 开发服务器首次编译，**不能用于生产性能判断**。本次未测并发、p95、浏览器完整学习入口或学生服务，因此尚不切换默认模式。影子日志现带课程 ID、结果是否一致和教师 API 耗时；只在显式启用 `shadow` 时产生。

> 本次盘点只新增本文档，未切换开关、改动业务代码、执行数据库迁移或触碰生产部署。403 习题评分报错按既定范围不列为解耦阻断项。
