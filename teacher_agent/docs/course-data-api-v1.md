# MENTRA 课程数据库与接口对接说明（v1）

本文档面向教师端、学生智能体、SaaS 基座和运维开发人员，说明完整课程体系的数据持久化方式、写入链路、读取接口与后续对接边界。

## 1. 建设目标

课程材料解析结果和教学中间产物不能只保存在浏览器或临时文件中。当前实现提供以下能力：

- 教师端课程数据持久化到 PostgreSQL；
- 生成任务、审核过程和发布结果全程保留；
- 产物保存原始材料 ID、原始页码和文件哈希，可追溯来源；
- 学生智能体只能通过标准接口读取教师审核或发布后的数据；
- 保留本地 JSON 存储作为桌面开发环境的兼容方案；
- 接口采用 `/api/course-data/v1` 版本前缀，便于以后独立部署为 SaaS 服务。

## 2. 当前架构

```text
教师端界面
  │
  ├─ 创建课程 / 编辑课程结构 / 上传与解析材料
  ├─ 创建生成任务 / 生成中间产物
  └─ 教师修改 / 审核 / 发布
        │
        ▼
course-space-storage.ts（兼容仓储层）
  ├─ 本地 JSON 与文件存储
  └─ course-space-storage-adapter.ts（统一适配边界）
        ├─ course-space-database.ts（课程领域表）
        └─ @openmaic/storage（Agent Session / 事件流）
        │
        ▼
mentra_* 数据表
        │
        ▼
/api/course-data/v1/*
  ├─ SaaS 服务健康检查
  ├─ 已审核产物读取
  └─ 已发布知识包读取 → 学生智能体
```

当前采用兼容双写：先保留既有本地文件，再写 PostgreSQL。没有配置数据库时，数据库操作自动跳过，现有桌面版本仍可运行；配置数据库后，数据库写入失败会使本次服务请求失败，从而避免将失败误报为成功。

## 3. 关键代码位置

| 文件 | 职责 |
|---|---|
| `lib/server/course-space-database.ts` | PostgreSQL 连接、建表、Upsert 和数据库读取 |
| `lib/server/course-space-storage-adapter.ts` | 自定义 `@openmaic/storage` 适配层；统一课程数据写入、教师会话、事件回放和恢复 |
| `lib/server/course-space-storage.ts` | 现有课程仓储兼容层，负责文件存储与数据库双写 |
| `lib/course-space/types.ts` | 课程、材料、任务、产物、引用和知识包 TypeScript 契约 |
| `app/api/course-data/v1/health/route.ts` | 数据库健康状态接口 |
| `app/api/course-data/v1/courses/[courseId]/artifacts/route.ts` | 已审核产物读取接口 |
| `app/api/course-data/v1/courses/[courseId]/knowledge-package/route.ts` | 学生知识包读取接口 |
| `app/api/course-space/**` | 教师端创建、生成、审核与发布接口 |
| `app/api/course-space/[courseId]/agent/route.ts` | 教师工作区持久化对话、工作流路由与会话回放接口 |

## 4. 数据库配置

推荐为课程体系使用独立连接变量：

```env
COURSE_DATABASE_URL=postgresql://mentra_user:password@postgres.example.com:5432/mentra
```

若未设置 `COURSE_DATABASE_URL`，系统会尝试复用：

```env
DATABASE_URL=postgresql://mentra_user:password@postgres.example.com:5432/mentra
```

连接优先级：

1. `COURSE_DATABASE_URL`
2. `DATABASE_URL`
3. 都未设置时使用 `local-fallback`

数据库 Schema 会在首次数据库操作时通过事务自动创建，无需手工执行 SQL。连接池当前最大连接数为 8。

生产环境建议：

- 使用 PostgreSQL 14 或更高版本；
- 使用独立数据库用户，并限制到 MENTRA 所在 Schema；
- 通过 SaaS 密钥管理服务注入连接字符串；
- 不要将数据库 URL 提交到 Git；
- 数据库健康接口不会返回连接字符串或密码。

## 5. 数据表设计

所有表使用 `mentra_` 前缀，避免和 OpenMAIC 原有持久化表冲突。

### 5.1 `mentra_courses`

保存课程基础信息、教师归属、课程—模块—课时结构、材料元数据和当前活动知识包 ID。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `TEXT PK` | 课程 ID |
| `teacher_id` | `TEXT` | 教师或租户内教师 ID |
| `status` | `TEXT` | `draft`、`active`、`archived` |
| `title` | `TEXT` | 课程名称 |
| `payload` | `JSONB` | 完整 `CourseSpace` 对象 |
| `created_at` | `BIGINT` | 毫秒时间戳 |
| `updated_at` | `BIGINT` | 毫秒时间戳 |

索引：`teacher_id + updated_at DESC`。

### 5.2 `mentra_material_extractions`

保存材料解析文本、分页文本块、公式及原始材料哈希。

| 字段 | 类型 | 说明 |
|---|---|---|
| `material_id` | `TEXT PK` | 材料 ID |
| `course_id` | `TEXT` | 所属课程 |
| `source_sha256` | `TEXT` | 原始文件内容哈希 |
| `payload` | `JSONB` | `CourseMaterialExtraction`，包含 `chunks` 和 `formulas` |
| `created_at` / `updated_at` | `BIGINT` | 时间戳 |

每个文本块包含：

```json
{
  "id": "chunk-id",
  "materialId": "material-id",
  "page": 12,
  "text": "该页解析文本"
}
```

### 5.3 `mentra_artifact_jobs`

保存教师触发的单产物生成任务及进度。关键字段为 `course_id`、`teacher_id`、`artifact_type`、`status`、`payload`、`created_at` 和 `updated_at`。

任务状态：

```text
queued → running → review → approved
                   └────────→ failed
```

### 5.4 `mentra_course_artifacts`

保存生成后的中间产物、HTML、审核状态、来源引用和衍生文件位置。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `TEXT PK` | 产物 ID |
| `job_id` | `TEXT` | 来源生成任务 |
| `course_id` | `TEXT` | 所属课程 |
| `teacher_id` | `TEXT` | 所属教师 |
| `artifact_type` | `TEXT` | 产物类型 |
| `status` | `TEXT` | `review`、`approved`、`published` |
| `payload` | `JSONB` | 完整 `CourseArtifactRecord` |
| `created_at` / `updated_at` | `BIGINT` | 时间戳 |

支持的 `artifact_type`：

| 值 | 含义 |
|---|---|
| `course-outline` | 课程教学大纲 |
| `module-plan` | 模块教学计划 |
| `lesson-courseware` | 课时 PPT / 互动课件 |
| `narration` | 讲稿与配音 |
| `exercise-set` | 习题与答案 |
| `assessment-rubric` | 测验与评分量规 |
| `pbl-project` | PBL 项目 |

### 5.5 `mentra_knowledge_packages`

保存教师发布给学生智能体的不可变版本化知识包。关键字段为 `course_id`、`teacher_id`、`version`、`status`、`payload`、`created_at`、`published_at`；`course_id + version` 唯一。

状态包括：

- `draft`：尚未发布；
- `published`：当前可供学生读取；
- `superseded`：已有更新版本，保留用于审计与回溯。

### 5.6 课程知识中台标准表

课程知识图谱不放在 `mentra_courses.payload` 中，而使用独立、版本化的标准表：

| 表 | 作用 |
|---|---|
| `mentra_course_graph_versions` | 图谱版本、状态、材料哈希集合和发布时间 |
| `mentra_course_graph_nodes` | 课程、模块、课时、知识点、目标、活动、评价、产物片段和来源块 |
| `mentra_course_graph_edges` | `contains`、`prerequisite-of`、`teaches`、`assesses`、`evidenced-by` 等关系 |
| `mentra_course_graph_evidence` | 节点到材料、文本块、原始页码、幻灯片号和 SHA-256 的追溯记录 |
| `mentra_course_access_grants` | 租户内教师、学生、班级或服务账号的课程角色授权 |

图谱状态为 `draft → review → published → superseded`。学生智能体只能读取
`published` 版本；教师修改时创建新版本，不直接覆盖已发布图谱。

## 6. 数据与二进制文件的存放边界

数据库保存结构化数据、内容正文、HTML、引用、状态和文件定位信息。以下二进制内容目前不直接写入 PostgreSQL：

- 教师上传的 PPT、PPTX、PDF、Word 原文件；
- 生成的 `.docx`；
- 互动课件媒体文件。

这些内容继续由文件或对象存储保存，数据库记录 `storageKey`、`wordStorageKey`、`classroomId` 或 `classroomUrl`。部署到 SaaS 时可将文件实现替换为 S3/OSS，而无需修改学生数据接口。

## 7. 自动写入时机

| 教师端动作 | 数据库写入 |
|---|---|
| 创建或修改课程 | Upsert `mentra_courses` |
| 上传材料 | 更新课程 `payload.materials`；原文件写文件/对象存储 |
| 解析材料 | Upsert `mentra_material_extractions`，并更新课程材料状态 |
| 创建生成任务 | Upsert `mentra_artifact_jobs`，状态为 `queued` |
| 任务执行和进度变化 | 更新同一任务记录，不新增重复任务 |
| 生成中间产物 | Upsert `mentra_course_artifacts`，状态为 `review` |
| 保存教师修改 | 更新产物正文、HTML、审核备注和 `updatedAt` |
| 审核通过 | 产物状态改为 `approved`，写入 `approvedAt` |
| 发布课程知识包 | 写入新版本 `mentra_knowledge_packages`；旧版本改为 `superseded`；产物改为 `published` |

所有数据库写入均使用主键冲突更新，适合任务重试和服务重启后的幂等恢复。

## 8. API 通用约定

基础地址示例：

```text
https://mentra.example.com/api/course-data/v1
```

成功响应：

```json
{
  "success": true,
  "apiVersion": "v1"
}
```

失败响应：

```json
{
  "success": false,
  "errorCode": "INVALID_REQUEST",
  "error": "面向用户或调用方的错误说明",
  "details": "可选的技术细节"
}
```

| HTTP 状态码 | 含义 |
|---|---|
| `200` | 查询成功 |
| `201` | 创建或发布成功 |
| `202` | 异步任务已接收 |
| `400` | 参数错误 |
| `404` | 课程、材料、任务或知识包不存在 |
| `409` | 状态冲突，例如没有审核通过的产物或缺少来源引用 |
| `500` | 服务端或数据库异常 |

## 9. 数据库健康检查

### 请求

```http
GET /api/course-data/v1/health
```

### PostgreSQL 正常时

```json
{
  "success": true,
  "apiVersion": "v1",
  "database": {
    "configured": true,
    "connected": true,
    "driver": "postgresql",
    "database": "mentra"
  }
}
```

### 未配置数据库时

```json
{
  "success": true,
  "apiVersion": "v1",
  "database": {
    "configured": false,
    "connected": false,
    "driver": "postgresql"
  }
}
```

```bash
curl https://mentra.example.com/api/course-data/v1/health
```

## 10. 学生智能体读取已审核产物

### 请求

```http
GET /api/course-data/v1/courses/{courseId}/artifacts
```

该接口只返回 `approved` 和 `published` 产物，不返回 `review` 草稿。

### 响应示例

```json
{
  "success": true,
  "apiVersion": "v1",
  "source": "database",
  "courseId": "sx2QQqfZUm48",
  "artifacts": [
    {
      "id": "artifact-id",
      "type": "course-outline",
      "title": "《现代交换原理》课程教学大纲",
      "content": "Markdown 正文",
      "htmlContent": "<h1>HTML 正文</h1>",
      "status": "published",
      "scope": { "type": "course" },
      "citations": [
        {
          "materialId": "material-id",
          "sourceName": "第1章 绪论.ppt",
          "page": 2,
          "sourceSha256": "原始文件哈希"
        }
      ],
      "approvedAt": 1788670000000,
      "updatedAt": 1788670000000
    }
  ]
}
```

`source` 的可能值：

- `database`：从 PostgreSQL 返回；
- `local-fallback`：当前未配置 PostgreSQL，使用本地兼容存储。

TypeScript 调用示例：

```ts
const response = await fetch(
  `${MENTRA_BASE_URL}/api/course-data/v1/courses/${courseId}/artifacts`,
  { headers: { Authorization: `Bearer ${serviceToken}` } },
);
if (!response.ok) throw new Error(`MENTRA request failed: ${response.status}`);
const data = await response.json();

for (const artifact of data.artifacts) {
  for (const citation of artifact.citations) {
    console.log(citation.materialId, citation.page, citation.sourceSha256);
  }
}
```

## 11. 学生智能体读取已发布知识包

### 请求

```http
GET /api/course-data/v1/courses/{courseId}/knowledge-package
```

该接口只返回最新的 `published` 知识包。若课程没有发布知识包，返回 `404`。

### 响应示例

```json
{
  "success": true,
  "apiVersion": "v1",
  "source": "database",
  "courseId": "sx2QQqfZUm48",
  "knowledgePackage": {
    "id": "package-id",
    "teacherId": "teacher-id",
    "courseId": "sx2QQqfZUm48",
    "version": 3,
    "status": "published",
    "entries": [
      {
        "id": "entry-id",
        "courseId": "sx2QQqfZUm48",
        "moduleId": "optional-module-id",
        "lessonId": "optional-lesson-id",
        "title": "知识条目标题",
        "content": "教师审核后的正文",
        "citations": [
          {
            "materialId": "material-id",
            "sourceName": "课程材料.pptx",
            "slide": 8,
            "sourceSha256": "原始文件哈希"
          }
        ],
        "approvedAt": 1788670000000
      }
    ],
    "createdAt": 1788670000000,
    "publishedAt": 1788670000000
  }
}
```

建议学生智能体优先使用知识包接口，而不是直接读取产物接口：知识包代表教师明确发布的稳定版本，适合作为检索增强、问答和学习诊断的知识来源。

## 11.1 学生智能体读取课程知识图谱

```http
GET /api/course-data/v1/courses/{courseId}/knowledge-graph
GET /api/course-data/v1/courses/{courseId}/knowledge-graph?nodeType=knowledge-point
GET /api/course-data/v1/courses/{courseId}/knowledge-graph?lessonId={lessonId}
```

接口只返回教师已发布的图谱。节点同时包含 `evidence`，调用方可沿
`materialId + chunkId + page/slide + sourceSha256` 返回原始材料证据。

教师工作区使用独立接口管理草稿：

```http
GET  /api/course-space/{courseId}/knowledge-graph
POST /api/course-space/{courseId}/knowledge-graph
     { "action": "bootstrap" }
PUT  /api/course-space/{courseId}/knowledge-graph
POST /api/course-space/{courseId}/knowledge-graph/publish
     { "version": 1 }
```

`bootstrap` 只根据真实课程结构与已解析页码建立可追溯图谱骨架，不让模型虚构知识点。
后续知识抽取 Job 在该草稿版本中增加 `knowledge-point`、`learning-objective`、
`activity` 和 `assessment-item` 节点，再进入教师审核。

## 12. 教师端现有写入接口

这些接口仍位于 `/api/course-space`，内部已经接入数据库双写。其他教师端模块可直接复用，不应绕过仓储层直接写表。

### 创建课程

```http
POST /api/course-space
Content-Type: application/json

{
  "teacherId": "teacher-id",
  "title": "现代交换原理",
  "subject": "通信工程",
  "gradeBand": "本科",
  "term": "2026 秋"
}
```

### 上传与解析材料

```http
POST /api/course-space/{courseId}/materials
Content-Type: multipart/form-data

file=<PPT/PPTX/PDF/Word 文件>
```

单文件当前限制为 80 MB。上传只保存，不自动解析。随后调用：

```http
POST /api/course-space/{courseId}/materials/{materialId}/parse
```

返回 `202` 后异步解析，材料状态依次为 `uploaded → parsing → ready`，失败时为 `failed`。

### 创建教学产物任务

```http
POST /api/course-space/{courseId}/jobs
Content-Type: application/json

{
  "scope": { "type": "module", "moduleId": "module-id" },
  "artifactTypes": ["module-plan"]
}
```

虽然接口接受数组，当前产品流程建议每次只创建一个产物，以保持“单任务—审核—可视化”的流程一致性。

生成范围可以是：

```json
{ "type": "course" }
```

```json
{ "type": "module", "moduleId": "module-id" }
```

```json
{ "type": "lesson", "lessonId": "lesson-id" }
```

### 查询任务

```http
GET /api/course-space/jobs/{jobId}
```

响应中的 `done` 在状态为 `review`、`approved` 或 `failed` 时为 `true`。

### 保存或审核产物

```http
PATCH /api/course-space/{courseId}/artifacts/{artifactId}
Content-Type: application/json

{
  "action": "approve",
  "content": "教师确认后的 Markdown 内容",
  "reviewerNote": "审核说明"
}
```

`action` 可取 `save` 或 `approve`。产物没有任何来源引用时不能审核通过。

### 发布知识包

```http
POST /api/course-space/{courseId}/publish
```

发布门禁：

- 至少存在一个 `approved` 产物；
- 每个待发布产物至少有一条来源引用；
- 发布后产生递增版本号；
- 旧发布版本变为 `superseded`；
- 已发布产物不能直接修改，需要重新生成版本。

## 13. 学生智能体推荐接入流程

```text
1. 使用平台身份获取 courseId
2. GET knowledge-package
3. 缓存 package.id + version
4. 将 entries 切分并建立向量索引
5. 回答时同时返回 citations
6. citations.page 或 citations.slide 显示给学生
7. 定时比较 version；仅在版本变化时重建索引
```

学生回答建议携带以下追溯对象：

```json
{
  "answer": "……",
  "sources": [
    {
      "materialId": "material-id",
      "sourceName": "第2章 交换技术基础.ppt",
      "page": 16,
      "sourceSha256": "sha256"
    }
  ]
}
```

## 14. SaaS 多租户对接要求

数据结构已经保留 `teacherId`，但当前本地首版尚未实现完整身份认证与租户隔离。部署到 SaaS 基座前，对接方需要完成：

- 从登录令牌或服务令牌中获取 `tenantId`、`teacherId`、`studentId`；
- 禁止信任客户端自行提交的 `teacherId`；
- 教师写接口校验课程归属；
- 学生读接口校验选课、班级或授权关系；
- 推荐增加 `tenant_id` 独立列并纳入所有查询条件和复合索引；
- 为服务间调用增加 Bearer Token、mTLS 或 API Gateway 鉴权；
- 将审计日志记录到独立表或平台日志系统。

因此，当前 `/api/course-data/v1` 适合作为内部服务接口；在完成鉴权中间件前，不应直接暴露到公网。

### 14.1 教师工作区持久化会话

配置 PostgreSQL 后，教师工作区使用 `@openmaic/storage` 的
`PgAgentSessionStore`，并使用独立的 `mentra_teacher_agent_*` 表保存：

- 会话归属、课程 ID、状态、尝试次数和执行租约；
- 用户消息与智能体最终回复；
- `session_start`、`session_resumed`、`checkpoint`、`session_interrupted` 等事件；
- 崩溃后可重新领取的任务状态。

当前单教师首版使用稳定会话 ID：`teacher-{courseId}-default`。刷新教师工作区时，
前端调用以下接口恢复历史对话：

```http
GET /api/course-space/{courseId}/agent?sessionId=teacher-{courseId}-default
```

普通分析问题和“生成大纲/课件/讲稿/习题”等工作流意图都会先写入会话事件流；
后者只保存路由结果，实际产物仍由既有生成—审核—发布流程完成，不由聊天模型直接生成。

未配置数据库时，该接口保持原有无状态行为，不影响本地文件模式。生产环境默认拒绝
公开使用开发持久化令牌；`PERSISTENCE_ALLOW_INSECURE_DEV_AUTH=true` 仅限可信内网的
单用户部署，SaaS 必须替换为服务端身份认证。

## 15. 本地数据迁移与上线注意事项

当前已有课程可能只存在 `data/course-spaces`。配置 PostgreSQL 后，新建或再次保存的数据会自动写入数据库，但历史数据不会凭空迁移。

正式切换前建议执行一次迁移工具，按以下顺序 Upsert：

1. courses
2. material extractions
3. artifact jobs
4. course artifacts
5. knowledge packages

迁移采用原 ID，不重新生成 ID；迁移后比较各类记录数量和知识包版本。完成验证前应保留本地目录备份。

## 16. 当前限制与后续建议

当前已完成：

- PostgreSQL Schema 自动创建；
- 课程核心对象幂等写入；
- 数据库/本地兼容读取；
- 学生安全读取接口；
- 知识包版本与来源追溯。

后续建议按优先级实现：

1. SaaS 身份认证与 `tenant_id` 隔离；
2. 历史本地数据一键迁移命令；
3. 将 PostgreSQL 提升为课程元数据唯一事实源，本地 JSON 降为开发模式；
4. 原始文件与 Word 文件迁移至 S3/OSS；
5. 数据库事务或 Outbox，保证文件/对象存储和数据库最终一致；
6. 学生接口分页、ETag、版本增量同步和速率限制；
7. OpenAPI 3.1 描述和自动生成客户端 SDK。

## 17. 联调检查清单

- [ ] 配置 `COURSE_DATABASE_URL`
- [ ] 调用 `/api/course-data/v1/health`，确认 `connected=true`
- [ ] 创建测试课程并上传材料
- [ ] 解析材料，确认页码和公式写入
- [ ] 创建单个产物任务并等待进入 `review`
- [ ] 审核产物，确认学生产物接口可以读取
- [ ] 发布知识包，确认版本号递增
- [ ] 学生智能体读取知识包并展示来源页码
- [ ] 验证未审核草稿不会进入学生接口
- [ ] 验证跨教师、跨课程访问被 SaaS 鉴权层拒绝

## 18. 版本与兼容约定

- 当前接口版本：`v1`
- 兼容性变更：在 `v1` 内增加可选字段
- 破坏性变更：新建 `/api/course-data/v2`
- 调用方必须忽略不认识的新增字段
- 调用方不应依赖 JSON 字段顺序
- 时间字段当前统一为 Unix 毫秒时间戳

## 19. 课程知识抽取 Job

知识抽取不是同步聊天回复，也不会自动发布。服务端复用 OpenMAIC 的材料解析结果、
统一模型路由和 `PgAgentSessionStore`，按以下阶段执行并持久化：

`queued → retrieving → extracting → merging → aligning → persisting → review`

任务表为 `mentra_course_graph_jobs`。每条任务保存课程、图谱版本、OpenMAIC 会话 ID、
阶段、进度、错误和抽取统计；会话事件继续存入 `mentra_teacher_agent_*` 表，因此任务中断后
可追踪执行尝试和 checkpoint。生成结果写回当前图谱草稿版本，包括：

- `knowledge-point`：知识点节点；
- `learning-objective`：课程目标节点；
- `prerequisite-of`：知识点先修关系；
- `teaches` / `aligned-with`：知识点、目标与课时的对齐关系；
- `evidenced-by`：知识节点到原始材料片段的证据关系。

每个抽取节点至少需要一条有效 `chunkId + materialId + page + sourceSha256` 证据，模型输出中
不存在的片段 ID 和课时 ID 会被丢弃。没有有效证据的知识点不会写入图谱。

### 19.1 启动任务

```http
POST /api/course-space/{courseId}/knowledge-graph/extract
Content-Type: application/json

{"teacherId":"local-teacher"}
```

前置条件：已配置 `COURSE_DATABASE_URL`、已建立未发布的图谱骨架，并至少存在一份 `ready`
材料。接口返回 `202` 和任务对象。同一图谱版本已有排队或运行任务时返回现有任务，避免重复执行。

### 19.2 查询任务

```http
GET /api/course-space/{courseId}/knowledge-graph/extract
GET /api/course-space/knowledge-graph/jobs/{jobId}
```

第一个接口返回课程的任务历史，第二个接口用于进度轮询。任务进入 `review` 后，教师在
`/course-space/{courseId}/knowledge-graph` 核对知识点、目标、关系和页码证据。
失败任务或租约超过两分钟未更新的中断任务可以通过以下接口恢复；OpenMAIC 会话存储会记录
`session_resumed` 事件：

```http
POST /api/course-space/knowledge-graph/jobs/{jobId}
```

### 19.3 审核与发布约束

审核页会先把知识点和课程目标标记为 `approved`，再调用现有图谱发布接口。服务端拒绝发布
没有知识点、没有来源证据，或仍含未审核知识点/目标的图谱。学生接口始终只返回
`published` 版本。
