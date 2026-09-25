# 平台对接分析 · SZU-AgentEduPlatform

**问题**：SaaS 平台（SZU-AgentEduPlatform / OpenMAIC，下称「平台」）的接口，和本仓库
的学生端，能对应上吗？学生端还差什么？

**性质**：本文是**逐行核对代码的实测结果**，不是设计推演。每条结论都带 `file:line`，
可以复核。核对日期 **2026-09-22**。

**读者**：要动手做对接的人。**先读「结论」，再读第 1 节**——第 1 节讲一个会让所有
后续判断跑偏的坑。

> 本系统对外提供哪些接口，见 [`apps/API-SAAS.md`](API-SAAS.md)；
> 会话层接口本身见 [`apps/API.md`](API.md)。

---

## 结论

**对应不上。但缺的不是"学生端的几个接口"，而是缺中间一整层适配。**

理由有三条，一条比一条根本：

**① 平台自己声明的集成边界里，没有学生侧。**

`deploy/saas-split/integration-manifest.json` 只声明了三块投递单元——
教师工作台、课堂播放器、教师智能体 API；`packages/integration-contract/openapi.yaml`
（65 行）只声明了 3 条 `/teacher-agent/*`。**学生侧从未进入正式契约**，
现有那些学生接口是"有文档、没进契约"的半成品对接面，随时可能变。

**② 两边不在一个层次上，是互补而非重叠。**

| | 平台 | 本仓库 |
| --- | --- | --- |
| 定位 | 内容生产 + 发布门禁 + 学情仓库 | 课堂运行时 |
| 提供 | 知识包 / 图谱 / 教学产物 / 互动课件 | 会话状态机 / 阶段推进 / 判星 / 学情报告 |
| 缺 | **没有会话、没有阶段推进、没有判星** | **没有内容来源** |

平台 `docs/course-data-api-v1.md` §11/§13 自己写明了期望的用法：把知识包切片建索引、
做带引用的问答——**它期望的「学生智能体」是一个 RAG 知识源，不是课堂**。

**③ 数据模型对不上，而且有一处几乎不可能无损转换。**

- 层级：平台 `course → modules → lessons → files`，本仓库 `courses → lessons → segments`
- 素材：平台是**互动课件**（`stage` + `scenes`，四类场景 + 22 种播放动作），
  本仓库是**单个视频 + 时间轴**，且项目自己不建播放器，只提供挂载点
- ID：平台 `courseId`/`classroomId`/`artifactId`/`CLS-*`，本仓库 `ch3-process-scheduling`/`seg-001`/`KP-001`

**真正的工作量在中间那层适配**（平台的已发布内容 → 本仓库的课时模型；本仓库的学情
→ 平台的班级学生记录）。这两件事都**不存在现成实现**。

---

## 1. 核对基准：本机有两份平台代码，它们不一样

**这一节必须放在最前面**——读错副本会让后续所有判断跑偏。

| 副本 | 路径 | Class 层 | `deploy/saas-split/` |
| --- | --- | --- | --- |
| A | `F:\project\AIedu\SZU-AgentEduPlatform`（git `7538cd8`） | ❌ 无 `app/api/classes/` | ❌ 缺 |
| B | `F:\project\SZU-AgentEduPlatform-main\SZU-AgentEduPlatform-main`（ZIP 解压，非 git） | ✅ 有 | ✅ 有 |

两份的差异**只有两个文件**：`lib/course-space/types.ts` 与
`lib/course-space/teacher-agent-intent.ts`，差异内容正好是 **Class 层**：

```ts
// CourseLessonFile / CourseMaterialRecord / CourseArtifactRecord 各加四个字段
classVisible?: boolean;
activatedAt?: number;
classPublicationId?: string;   // 形如 CLS-A-{id} / CLS-M-{id} / CLS-F-{id}
classPublishedAt?: number;

// 新类型
export interface CourseStudentLearningState {
  studentId: string; name: string; studentNumber?: string; className?: string;
  status: 'not-started' | 'learning' | 'completed' | 'needs-attention';
  progress: number; completedResourceIds: string[]; lastActiveAt?: number;
}

// CourseSpace 新增
classStudents?: CourseStudentLearningState[];
```

**其余平台代码是同一版本**（含 `student-agent/v1` 三条路由、鉴权、
`middleware.ts`——把行尾 CRLF/LF 归一后逐字节相同）。

> **踩过的坑**：对着副本 A 分析，会得出「`PUT /api/classes/{courseId}/students`
> 不存在、清单是编的」这种错误结论。实际上那份清单描述的是**副本 B**，完全属实。

---

## 2. 平台的集成边界：只有教师侧

`deploy/saas-split/integration-manifest.json` 逐字：

```json
{ "version": "1.0", "strategy": "incremental-compatible-split",
  "deliveryUnits": {
    "teacherWorkspace": { "entry": "/teacher-workspace?workspace={courseId}",
                          "legacyEntry": "/course-space?workspace={courseId}", "embed": true },
    "classroomPlayer":  { "entry": "/classroom-player/{classroomId}",
                          "legacyEntry": "/classroom/{classroomId}", "embed": true },
    "teacherAgentApi":  { "capabilities": "/api/teacher-agent/capabilities",
                          "plan": "/api/teacher-agent/plan",
                          "execute": "/api/teacher-agent/execute",
                          "openapi": "packages/integration-contract/openapi.yaml" } },
  "legacyRoutesPreserved": true }
```

`packages/integration-contract/openapi.yaml`（65 行，OpenAPI 3.1.0，`servers: [{url: /api}]`）
**只声明了 3 条 `/teacher-agent/*`**，没有任何学生侧路径。

**含义**：学生侧在平台的正式契约里是**未定义**的。不要把这些接口当稳定契约来设计
架构——它们没有版本承诺，也（见第 3 节）没有和 Class 层对齐。

---

## 3. 平台有两条学生边界，而且互相打架

| | `student-agent/v1`（3 条 GET） | `classes/*`（Class 层） |
| --- | --- | --- |
| 鉴权 | `Authorization: Bearer <STUDENT_AGENT_API_KEY>` | **无**（靠全局 middleware cookie） |
| 产物可见性 | `status === 'published'` | `status === 'published' && classVisible && classPublicationId` |
| 定位 | 服务端到服务端（密钥不能进浏览器） | 教师策展的「班级」体验 |
| 入口 | `GET /api/student-agent/v1/courses/{courseId}` | `GET /api/classes`、`GET /api/classes/{courseId}` |

逐行核对位置：

- `app/api/student-agent/v1/courses/[courseId]/route.ts:25`
  → `artifacts.filter((artifact) => artifact.status === 'published')`
- 同文件 `:44` → `files: (lesson.files ?? []).filter((file) => file.status === 'ready')`
- `app/api/classes/[courseId]/route.ts:18,20,24`
  → 三处都带 `item.classVisible && item.classPublicationId`

### ⚠️ 由此产生的越权面

同一个产物，教师**没勾**「发布到班级」（`classVisible = false`），在
`student-agent/v1` 里**照样可见**——而那条边界手里还握着服务端密钥。
两条边界对「学生可见」的定义不一致。这是真实的口子，不是理论问题。

### 还有一处更松的

`app/classroom-player/[id]/page.tsx` 只是 `app/classroom/[id]/page` 的 4 行 re-export，
实际加载走 `fetch('/api/classroom?id=')`，**无鉴权、且不校验产物的发布关联**，
比 `student-agent/v1/classrooms/{id}`（要求产物已发布 + 知识包已发布）弱。

**走嵌入播放器那条路，权限比走 API 低。** 这一点在决定用哪种方式接课件时很关键。

---

## 4. 平台期望的「学生智能体」是 RAG 源，不是课堂运行时

`docs/course-data-api-v1.md` §11 与 §13 逐字：

> 建议学生智能体优先使用知识包接口，而不是直接读取产物接口：知识包代表教师明确发布的
> 稳定版本，适合作为检索增强、问答和学习诊断的知识来源。

> 1. 使用平台身份获取 courseId 2. GET knowledge-package 3. 缓存 package.id + version
> 4. 将 entries 切分并建立向量索引 5. 回答时同时返回 citations
> 6. citations.page 或 citations.slide 显示给学生 7. 定时比较 version；仅在版本变化时重建索引

**这是决定性的。** 平台期望的消费方式是「把知识包切片建索引，做带引用的问答」。
它没有会话、没有阶段推进、没有判星——那本来就是本系统的职责。

**所以不要指望平台提供 `/api/lesson`、`/api/session/*`。那不是它的事。**
要做的是在本系统加一层「从平台拉内容」的适配。

---

## 5. 逐字段映射

### 5.1 取内容这半条链

| 本仓库学生端要的 | 平台有吗 | 结论 |
| --- | --- | --- |
| 我的课程列表 | ❌ 5 条学生路由**全部**是 `{courseId}` 作用域；`GET /api/classes` 虽返回课程列表但是**教师视图**（按 `DEFAULT_TEACHER_ID` 过滤） | **两端都缺**（见 6.①） |
| 课程 → 课时结构 | ⚠️ 平台 `course → modules → lessons → files[ready]`；本仓库 `courses → lessons`（扁平，带 `week`/`chapter`） | **平台多一层 `modules`**，需拍平或扩展本仓库模型 |
| `lesson.segments`（带 `startSeconds`/`endSeconds` 的时间轴） | ⚠️ 平台没有时间轴。最近的是 `CourseLessonFileType` 里的 `narration-segments` / `courseware-pages`，但语义是**文本/Markdown 文件** | **模型不匹配** |
| `lesson.knowledgePoints: string[]` | ✅ 知识包 `entries[{title, content, citations}]` + 图谱 `knowledge-point` 节点 | **可映射**（取 `title`） |
| 判星用的 `kp_id`（`KP-001`） | ⚠️ 图谱节点与知识包 entries 都有 `id`，但没有 `KP-00N` 这种形式 | **需约定 id 映射** |
| `GET /api/lesson/video` → 单个视频 URL | ❌ 平台是**互动课件**：`stage` + `scenes`（`slide`/`quiz`/`interactive`/`pbl` 四类，配 22 种 Action：白板、聚光灯、激光笔…），二进制走 `classroom-media` | **模型不匹配，别做无损转换** |
| `POST /api/session/*`（会话状态机） | ❌ 完全没有 | **本仓库本职，不是缺口** |

### 5.2 回写学情这半条链

`PUT /api/classes/{courseId}/students`（前置：course 必须 `status === 'active'`，否则 404）

| 平台字段 | 本仓库导出 | 问题 |
| --- | --- | --- |
| `studentId`（必填） | `student_id` | ✅ 直接 |
| `name`（必填） | — | ❌ **本仓库只有 id，没有姓名** |
| `studentNumber?` / `className?` | — | ❌ 无 |
| `status`（必填，4 枚举） | — | ⚠️ 需从 `stars` 推导，无唯一解 |
| `progress`（0–100） | `stars`（0–5） | ⚠️ **语义不等价**：平台是课程进度，本仓库是掌握度。`mean(stars)/5*100` **是错的方向** |
| `completedResourceIds` | — | ❌ 平台的是 `CLS-A-`/`CLS-M-`/`CLS-F-` 资源 id，本仓库是 `seg-001`/`KP-001`，**没有映射表就只能留空** |
| `lastActiveAt?` | `updated_at` | ⚠️ 平台要 Unix ms，本仓库是 ISO 字符串 |

服务端会 clamp：`progress` 取 `Math.min(100, Math.max(0, Math.round(x)))`，
非有限值归 0；`completedResourceIds` 去重并丢弃空串；`status` 不在枚举内直接 400。
`studentId` 是 upsert 键——**没有花名册校验**，传谁就写谁。

---

## 6. 学生端还差什么（按硬度排序）

### ① 身份 +「我的课程」列表 —— 两端都空，链路上唯一全空的地方

平台 5 条学生路由**全部**是 `{courseId}` 作用域，得先知道 `courseId` 才能调任何一个；
`GET /api/classes` 返回的课程列表是教师维度。

本仓库这边 `student_id` 硬编码 `"student-001"`（`frontend/src/legacy/api.js:59`），
没有登录、没有选课、没有班级。

**「学生打开页面 → 看到自己该上的课」这一步，两边都没有接口。**
平台 `docs/course-data-api-v1.md` §14 自己也承认「学生端的选课/班级/授权校验也还待补」。

### ② `classVisible` / `classPublicationId` 这道闸接不到

Class 层用 `CLS-A-{id}` / `CLS-M-{id}` / `CLS-F-{id}` 标识「已发布到班级」的资源。
本仓库没有「资源 id」这个概念——`completedResourceIds` 因此无处可填。

### ③ 课件渲染路径没定

本仓库只会 `mountVideoPlayer(container, { video, startSeconds, onEnded })` 挂一个外部播放器；
平台是 `stage` + `scenes` + Action Engine。

**建议直接嵌入 `/classroom-player/{classroomId}`**（manifest 已标 `embed: true`），
不要尝试把 `stage+scenes` 翻译成 `segments`——那是几乎不可能无损的转换。
但注意第 3 节末尾那条：**嵌入路径的鉴权比 API 路径更松**。

### ④ CORS：平台侧完全没有配置

平台全仓库零 `Access-Control-Allow-*`（本仓库是另一回事 —— 它放行了本机来源，
见 `API-SAAS.md` §0）。浏览器跨域直连平台一律不行。教师端/学生端要直连
本系统或平台，都必须经同源反向代理。

### ⑤ 学情回写字段不等价

见 5.2。

---

## 7. 安全发现（平台侧）

| # | 发现 | 位置 |
| --- | --- | --- |
| 1 | `student-agent/v1` 不看 `classVisible`/`classPublicationId`，与 Class 层判断冲突 | `student-agent/v1/courses/[courseId]/route.ts:25,44` |
| 2 | `/api/classroom?id=` 无鉴权、不校验发布关联（嵌入播放器实际走这条） | `app/api/classroom/route.ts` |
| 3 | `course-data/v1/*`（4 条）无鉴权，且产物多暴露 `approved` 状态 | `app/api/course-data/v1/**` |
| 4 | `classroom-media/*` 无任何授权（只做了路径安全：`media/`、`audio/` 白名单 + realpath 校验） | `app/api/classroom-media/**` |
| 5 | `PUT /api/classes/*/students` 无鉴权无角色校验，任何人可覆盖任何学生记录 | `app/api/classes/[courseId]/students/route.ts` |
| 6 | `middleware.ts` 的 `ACCESS_CODE` cookie 要求**没写进** `STUDENT_AGENT_COURSE_API.md`——照那份文档做服务端对接会吃 401 | `middleware.ts` vs `docs/STUDENT_AGENT_COURSE_API.md` |
| 7 | `mentra_course_access_grants`（租户隔离表）已定义，但**没有任何学生读路径查询它** | `lib/server/course-space-database.ts` |
| 8 | 平台 §14 自述：「当前 `/api/course-data/v1` 适合作为内部服务接口；在完成鉴权中间件前，不应直接暴露到公网」 | `docs/course-data-api-v1.md` §14 |

### 平台侧唯一的正式鉴权

`lib/server/student-agent-auth.ts`（18 行）：`Authorization: Bearer <STUDENT_AGENT_API_KEY>`，
未配置密钥 → **503**，token 不符 → **401**，`timingSafeEqual` 常数时间比较。
**只保护 `student-agent/v1` 那 3 条。**

两个独立闸门容易漏掉的是第一个：

1. **`middleware.ts`** —— 只要设了 `ACCESS_CODE`，**所有 `/api/*`** 都要求一个
   HMAC 签名的 `openmaic_access` cookie（7 天 TTL）。只放行 `/api/access-code/*`
   和 `/api/health`。**只有 Bearer token 的服务端调用会吃 401**，除非先走
   `POST /api/access-code/verify` 拿到 cookie，或者干脆不设 `ACCESS_CODE`。
2. **`authorizeStudentAgent`** —— 只管 `student-agent/v1`。

### 两条同样的数据源，一条没有鉴权

平台维护了**两套**读同样数据的接口：`student-agent/v1`（有 Bearer）和
`course-data/v1`（**无鉴权**），后者还多暴露 `approved` 状态（教师已审核未发布）。
`STUDENT_AGENT_COURSE_API.md` 推荐的是前者，但后者没有被废弃。

**对接时只用 `student-agent/v1` / `classes/*`；`course-data/v1` 应当视作内部接口。**

---

## 8. 建议的分工

`integration-manifest.json` 里 `classroomPlayer: { embed: true }` 其实已经给了答案：

```
┌────────────────────────────────────────────────┐
│  平台：内容生产 + 发布门禁 + 学情仓库            │
│        + 课件播放器（被嵌入）                    │
└────────────────────────────────────────────────┘
              ↕   ← 这一层要新建
┌────────────────────────────────────────────────┐
│  本仓库：课堂运行时（会话 / 判星 / 报告）        │
│          + 学生界面外壳                          │
└────────────────────────────────────────────────┘
```

**本次真正的工作量**：

1. **内容适配层** —— 平台的已发布内容（知识包 + 图谱 + `files[ready]`）→ 本仓库的
   `lesson-plan + segments + knowledge_points`
2. **学情回写映射** —— 本仓库的 `export` → `PUT /api/classes/{courseId}/students` 的字段
3. **身份打通** —— 见 6.①

### 动手前必须先定的两件事

- **身份怎么打通**（6.①）——这是链路上唯一两端都空的地方，不定就没法往下走
- **用哪条边界**（第 3 节）——建议用 `classes/*`，它是教师真正策展的「班级」视角，
  而且能看到 `classVisible` 闸；`student-agent/v1` 只适合做服务端的内容同步。

### 其他需要留意的

- 时间戳：平台一律 Unix ms，**除了 `classroom.createdAt` 是 ISO 8601 字符串**
- `knowledgePackage` 以 `version` + `publishedAt` 作为缓存键（§13）
- 响应可能新增字段，客户端**必须忽略未知字段**（§18）
- `interactive` 场景内嵌原始 HTML（iframe `srcDoc`），`content` 是未清理的 Markdown ——
  **渲染前自己消毒**
