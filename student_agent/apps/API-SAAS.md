# SaaS 底座 × 教师端 接口说明

本仓库的**课堂引擎**（`apps/server.py`）如何接进 SaaS 底座，以及教师端怎么调。

读者有两方：

- **SaaS 底座**（平台侧）—— 下发课时与身份、收集课堂数据；
- **教师端**（老师用的界面）—— 上传课时定义、看学情。

> 单看会话层的时序与字段，见 [`apps/API.md`](API.md)；学生端视角见
> [`../frontend/docs/api/后端接口说明.md`](../frontend/docs/api/后端接口说明.md)。
> 本文只讲**跨系统对接**这一层。

---

## 0. 先读：现状与边界

### 本系统提供什么

一个**按课时计划自动推进的课堂引擎**。底座把「这节课讲什么」交给它，它负责
把课带完（讲解 → 复述 → 探究 → 讨论），并按知识点记录掌握度。

**它不是**：课程管理系统、教务系统、学生信息系统、视频托管。课程目录、
视频地址、账号体系这些它都没有，要么由底座供给，要么用仓库自带的演示数据。

### ⚠️ 鉴权现状：没有

**所有接口目前都不鉴权。** 具体说：

- `POST /api/teacher/lesson` 会**直接写盘**，不需要任何凭证；
- `apps/start.py` 默认绑 `0.0.0.0`，同网段任何人都能调用；
- CORS **只放行本机来源**（`apps/server.py` 的 `allow_origin_regex` 匹配
  `localhost` / `127.0.0.1` 的任意端口，带 credentials）。所以本机前后端分端口
  联调是通的，但部署到真实域名、前后端不同源时会被浏览器拦。

对接时**必须**由底座侧兜住：加网关鉴权、限制网络可达、或按本文第 5 节补 token。
在这一条落地之前，**不要把本系统直接暴露到公网**。

### 接口成熟度一览

| 分类 | 接口 | 状态 |
| --- | --- | --- |
| 底座下发 | `POST /api/teacher/lesson` | ✅ 可直接用 |
| 底座下发 | `POST /api/session/start`（带 `student_id`） | ⚠️ 能用，但身份不校验 |
| 底座下发 | 教师身份 / 班级 / 选课关系 | ❌ **待补** |
| 底座回传 | `GET /api/session/{sid}/state` | ✅ 轮询可用 |
| 底座回传 | `GET /api/session/{sid}/messages` | ✅ 增量轮询 |
| 底座回传 | `GET /api/session/{sid}/export` | ✅ 学情报告 |
| 底座回传 | 事件主动推送（webhook / 回调） | ❌ **待补**，只能轮询 |
| 教师端 | `POST /api/teacher/lesson` / `GET .../{id}` | ✅ 可直接用 |

---

## 1. 角色与调用关系

```
┌───────────────┐   ① 下发课时定义 / 学生身份 / 课堂控制
│               │ ──────────────────────────────────────▶ ┌──────────────────────┐
│   SaaS 底座    │                                          │  本系统（课堂引擎）    │
│               │ ◀────────────────────────────────────── │  apps/server.py      │
└───────────────┘   ② 回传课堂状态 / 对话流 / 课后学情      └──────────────────────┘
        ▲                                                             ▲
        │ ③ 转发（教师端只跟底座说话）                                  │
        │                                                             │ ④ 直连
┌───────────────┐                                                     │
│    教师端      │ ────────────────────────────────────────────────────┘
└───────────────┘   （两条路径二选一，见第 4 节）
```

**职责划分**：底座管身份、课程目录、持久化归属；本系统管单节课的推进与判星。
两边共享的主键只有两个 —— **`lesson_id`** 和 **`session_id`**。

---

## 2. 底座 → 本系统

> 本节写的是**本系统对外提供什么**。至于真实的 SaaS 平台
> （SZU-AgentEduPlatform / OpenMAIC）到底暴露了哪些接口、能不能对上、差在哪 ——
> 见 [`apps/PLATFORM-INTEGRATION.md`](PLATFORM-INTEGRATION.md)。
> 那份的结论和本节的乐观基调不同，动手前先读它。

### 2.1 下发课时定义 ✅

老师（或底座的课程编辑模块）把一节课完整传进来，本系统落盘成
`lesson-data/lessons/<lesson_id>.json`，之后这节课就能被选课、开课、出报告。

```bash
POST http://<engine>/api/teacher/lesson
Content-Type: application/json

{
  "lesson_id": "ch4-deadlock",          # 主键。只允许字母数字与 . _ -，以字母数字开头，≤64 字符
  "lesson_title": "第4章 死锁",
  "course_id": "operating-systems",     # 底座侧的课程 id，本系统按它分组课程目录
  "course": "操作系统",
  "chapter": "第 4 周",
  "week": 4,
  "total_minutes": 45,
  "stages": [
    {"id": "guided_learning",  "enabled": true, "minutes": 20, "advance_when": "either"},
    {"id": "recap_discussion", "enabled": true, "minutes": 15, "advance_when": "either"},
    {"id": "deep_inquiry",     "enabled": true, "minutes": 10, "advance_when": "either"}
  ],
  "knowledge_points": [
    {"kp_id": "KP-401", "title": "死锁的定义",
     "定义": "两个或多个进程互相持有对方需要的资源并等待……",
     "检测问题": "死锁产生的四个必要条件分别是什么？",
     "掌握表现": "能说出四个必要条件并解释缺一不可。",
     "为什么这样设计": "", "如何实现": "", "解决什么实际问题": "", "关联学科": ""}
  ],
  "segments": [
    {"id": "seg-401", "minutes": 20, "order": 1, "title": "死锁与四个必要条件",
     "knowledge_point_ids": ["KP-401"], "knowledge_points": ["死锁"],
     "summary": "死锁的成因", "content": "互斥、持有并等待、不可剥夺、循环等待……"}
  ]
}
```

响应：

```json
{"ok": true, "lesson_id": "ch4-deadlock",
 "path": "lesson-data/lessons/ch4-deadlock.json",
 "knowledgePointCount": 1, "segmentCount": 1,
 "staleSessions": [], "note": ""}
```

**关键点：**

1. **这是一次 upsert**，同一个 `lesson_id` 再传即覆盖。
2. **校验就是开课时的校验**（`validate_plan`）。这里过了，开课就不会再因为
   计划本身失败。`stages[].id` 只能是 `guided_learning` / `recap_discussion` /
   `deep_inquiry` / `class_discussion`；`segments[].knowledge_point_ids` 必须
   指向本课已声明的 `kp_id`。
3. **`advance_policy` 可省**，省略时用内置默认（`wrap_up` / `advance` / 2 分钟 / 超时 3 分钟）。
4. **`staleSessions` 非空表示有正在上课的会话仍用旧版本。** 课时定义在 `/begin`
   那一刻被冻进会话状态（老师不该在上课中途被抽掉进度），所以**改完要新建会话
   才生效**；但知识点正文是每轮重读的，改错别字下一次心跳就生效。
5. **用内置课时的 id 可以覆盖它**（`ch3-process-scheduling`）。会生成 store 文件
   覆盖内置那份，删掉就恢复，内置文件本身不改写。

**错误码**：`lesson_id` 非法（`../evil`、`a/b`、`CON`）→ `400`；
定义校验不过 → `422`，`detail` 是中文问题清单。

### 2.2 下发学生身份 ⚠️

```bash
POST http://<engine>/api/session/start
{"session_id": "底座生成的会话 id", "student_id": "底座的学生 id", "lesson_id": "ch4-deadlock"}
```

- **`session_id` 由调用方决定**，本系统直接采用（不传才自己生成 `cls-xxxxxxxx`）。
  底座可以拿自己的会话 id 当 `session_id`，两边天然对齐。
- **`student_id` 决定掌握档案归属**：本系统按学生持久化在
  `runtime/students/<student_id>/mastery-state.json`，同一学生跨课次连续累计。
  底座应传真实的、稳定的学生标识。
- ⚠️ **本系统不校验这两个 id 的合法性，也不校验学生是否有资格上这节课。**
  鉴权和选课关系必须由底座负责（见第 5 节）。
- **`session_id` 会被拼进文件名**（`runtime/sessions/<sid>.json`），所以本系统
  按白名单校验：只放行 `[A-Za-z0-9._-]`、首字符须为字母数字，非法一律 `400`。
  底座生成 id 时请落在这个字符集内（UUID、`cls-xxxxxxxx` 都合规），
  不要把学号、邮箱、带 `/` 的路径当成 session id。

同一个 `session_id` 重复调用不会重置进行中的课堂，是幂等的。

### 2.3 下发教师身份 ❌ 待补

**目前没有教师身份这个概念。** `POST /api/teacher/lesson` 不记录是谁传的。
底座若需要审计「谁改了哪节课」，得在底座侧记，本系统这边补不出来。

### 2.4 控制课堂 ✅

```bash
POST /api/session/{sid}/begin        # 起课铃，开始上课
POST /api/session/{sid}/media/done   # 视频播完
POST /api/session/{sid}/stage/next   # 教师强制切下一幕
DELETE /api/session/{sid}            # 停课
```

也有统一入口，底座只对接一个即可：

```bash
POST /api/session/{sid}/event   {"type": "begin" | "media_done" | "next_stage"}
```

---

## 3. 本系统 → 底座

### 3.1 课堂状态 ✅（轮询）

```bash
GET /api/session/{sid}/state
```

```json
{"status": "running", "phase": "recap_discussion", "phase_name": "复述阶段",
 "stage_elapsed_minutes": 3.2, "stage_budget_minutes": 15.0,
 "lesson_elapsed_minutes": 23.5, "total_minutes": 45.0,
 "current_question": "死锁产生的四个必要条件分别是什么？",
 "advance_reason": "未达最短幕时长", "student_status": "active",
 "updated_at": "2026-09-22T15:51:41+08:00", "time_scale": 1.0,
 "stars": {"KP-401": 3},
 "segment_cursor": 1, "segment_total": 1, "played_media": [],
 "remaining_stages": ["deep_inquiry", "class_discussion"],
 "next_stage": "deep_inquiry",
 "available_actions": ["message", "media_done", "next_stage", "stop"]}
```

> 以上是字段全集（取自一次真实响应）。`status` ∈ `idle` / `running` / `ended`。

- `status` ∈ `idle` / `running` / `ended` —— 底座的课程状态机照这个落库。
- **`available_actions` 是权威的**：界面照它渲染按钮，别猜能不能按。
- 2 秒轮询一次足够。

### 3.2 对话流 ✅（增量轮询）

```bash
GET /api/session/{sid}/messages?since=<上次的 total>
```

```json
{"messages": [{"seq": 5, "role": "teacher", "text": "……", "at": "…", "phase": "…", "llm": true}],
 "total": 6, "student_id": "…"}
```

AI 主动说的话（心跳推进产生的）也在这里面，**轮询这一条就够把对话画完整**。

### 3.3 课后学情 ✅

```bash
GET /api/session/{sid}/export?fmt=json
```

```json
{"student_id": "…", "lesson_id": "ch4-deadlock", "session_id": "…",
 "lesson_elapsed_minutes": 38.2,
 "knowledge_points": [{"kp_id": "KP-401", "title": "死锁的定义", "stars": 4, "status": "接近掌握"}],
 "stage_snapshots": [{"type": "stage_snapshot", "snapshot_id": "ss-002",
   "student_id": "…", "lesson_id": "ch4-deadlock", "stage": "recap_discussion",
   "stage_elapsed_minutes": 9.0, "targets_closed": ["KP-401"], "targets_open": [],
   "stars_snapshot": {"KP-401": 3}, "evidence": "学生能用自己的话说明……",
   "occurred_at": "2026-09-22T14:23:00+08:00"}]}
```

**四个必须注意的点：**

1. **裸 JSON，没有 `{ok}` 信封**（和本文档其它接口都不一样），别去拆 `r.report`。
2. **响应头带 `Content-Disposition: attachment`** —— 这个接口是按「下载文件」
   设计的。`fetch` 仍能读到 body，但中文文件名可能出乱码。
3. **CORS 只放行本机来源** —— 底座**服务端**调用不受影响；浏览器从别的域调
   会被拦。教师端直连则必须解决（见第 4 节）。
4. **报告只在课已结束后才有内容**。`stars` 是**全课累计**的掌握度，不是本次课的。

星级口径以本仓库 `rules/interaction/MASTERY-STAR-RULES.md` 为准（0–5 星），
底座**不要自己算一套**。

### 3.4 主动推送 ❌ 待补

本系统**没有 webhook / 回调**。底座要感知「课结束了」「学生答完了」只能轮询
`/state`。若底座需要事件驱动，需要在会话层补一个出站回调，目前没有。

---

## 4. 教师端接入

教师端要做的事只有一件：**把课时定义传进来**（读回用 GET）。两条路径：

### 路径 A：直连本系统

```
教师端 ──▶ 本系统 /api/teacher/lesson
```

需要解决两件事：

1. **CORS**。本系统的 `CORSMiddleware` 只放行 `localhost` / `127.0.0.1`，
   教师端页面跑在别的域会被浏览器拦。两个办法：把域名加进
   `allow_origin_regex`（改本仓库 `apps/server.py`），或教师端经同源
   反向代理转发。
2. **鉴权**。见第 0 节 —— 现在是裸的，直连等于把写盘接口暴露给任何能访问到的人。

适合同机 / 内网部署，不适合公网。

### 路径 B：经底座转发（推荐）

```
教师端 ──▶ 底座（鉴权、审计）──▶ 本系统 /api/teacher/lesson
```

教师端只跟底座说话，底座负责鉴权、记录是谁改的、必要时做二次校验，再转发给
本系统。**本系统不需要暴露给教师端**，CORS 和鉴权问题一次性消失。

底座转发时建议补三件事：

- 记 `teacher_id` + 时间 + `lesson_id`（本系统不记，缺口 2.3）；
- 把 `course_id` 映射成自己课程体系里的 id；
- 上传前先 `GET /api/teacher/lesson/{id}` 看 `problems` 是否为空，
  再决定要不要转发。

### 老师实际要做的三步

1. 备好一节课的**阶段与时长**、**知识点**（每个至少 `kp_id` / `title` /
   `定义` / `检测问题` / `掌握表现`）、**段落**（每个要有 `content`，那是讲解的原始素材）；
2. `POST /api/teacher/lesson`；
3. `GET /api/teacher/lesson/{id}` 确认 `problems` 是空的 —— 空了就说明这课能开起来。

---

## 5. 鉴权与身份（待补）

**现状如实记录：没有鉴权。** 下面是要补的时候需要一起定的三件事，本文档
**不给未实现的方案当契约**：

| 要定的事 | 说明 |
| --- | --- |
| 调用方身份怎么传 | 是底座网关代管（本系统信任网络），还是底座签发 token（本系统校验并取 `teacher_id` / `student_id`）？ |
| 教师端接口的权限 | 谁能改哪节课？现在任何调用方都能覆盖任意 `lesson_id`，包括覆盖内置课时 |
| `session_id` 字符集 | 引擎侧已做白名单（见 2.2，非法即 400）。底座生成 id 时按该字符集来即可 |

**在补齐之前，部署上的最低要求**：只在内网可达，或前面挂一层带鉴权的网关。

---

## 6. 缺口清单

按对接影响排序：

| # | 缺口 | 影响 | 建议 |
| --- | --- | --- | --- |
| 1 | 全部接口无鉴权，`apps/start.py` 默认绑 `0.0.0.0` | 任何人都能覆盖课时，进而向课堂注入任意提示词内容 | **对接前必须由底座侧兜住** |
| 2 | ~~`session_id` 未清洗即拼进文件名~~ | ~~路径穿越写入~~ | **已修**：`_safe_sid` 白名单，非法返回 400（见 2.2） |
| 3 | 无事件推送，只能轮询 | 底座感知不到「课结束了」 | 轮询 `/state` 的 `status == "ended"`；需要事件驱动则要补出站回调 |
| 4 | 无教师身份 | 无法审计谁改了课时 | 底座侧记录 |
| 5 | 课程目录是演示数据，没有选课/班级概念 | 底座要自己管课程与学生归属 | 底座侧维护，用 `course_id` 关联 |
| 6 | 上传课时的判星靠关键词表，新知识点升不到 3 星以上 | 学情报告的星级偏低 | 见 `README.md` 已知缺口 |
| 7 | 视频走单个环境变量 `LESSON_VIDEO_URL` | 一节课一个视频，不能按 `lesson_id` 区分 | 需要多视频时改造 |

---

## 7. 接口总索引

| 方法 | 路径 | 谁调 | 用途 |
| --- | --- | --- | --- |
| POST | `/api/teacher/lesson` | 教师端 / 底座 | 上传（upsert）课时定义 |
| GET | `/api/teacher/lesson/{id}` | 教师端 / 底座 | 回读 + 校验结果 |
| GET | `/api/student/courses` | 学生端 | 课程目录（按 `course_id` 分组） |
| GET | `/api/lesson?lessonId=` | 学生端 | 课时详情、知识点、段落 |
| GET | `/api/lesson/video?lessonId=` | 学生端 | 视频地址（未配置返回 `null`） |
| POST | `/api/session/start` | 底座 / 学生端 | 进教室（幂等） |
| POST | `/api/session/{sid}/begin` | 底座 / 学生端 | 起课铃 |
| POST | `/api/session/{sid}/message` | 学生端 | 学生发言（所有阶段共用） |
| POST | `/api/session/{sid}/media/done` | 学生端 | 视频播完 |
| POST | `/api/session/{sid}/stage/next` | 教师端 / 底座 | 强制切下一幕 |
| POST | `/api/session/{sid}/event` | 任一端 | 统一事件入口（上面三个的合并版） |
| GET | `/api/session/{sid}/state` | 底座 / 学生端 | 课堂状态（轮询） |
| GET | `/api/session/{sid}/messages?since=N` | 底座 / 学生端 | 增量拉对话 |
| GET | `/api/session/{sid}/export?fmt=json\|md` | 底座 | 课后学情 |
| DELETE | `/api/session/{sid}` | 底座 / 教师端 | 停课 |

---

## 8. 平台对接实测 → 已独立成文

平台（SZU-AgentEduPlatform / OpenMAIC）接口的逐行核对结果，移到
[`apps/PLATFORM-INTEGRATION.md`](PLATFORM-INTEGRATION.md)。

**为什么单独放**：那份是**实测对方平台**得出的结论，和本文件「本系统对外提供什么」
是两个方向；它还带着一整套平台侧的行号引用和一个版本坑（那份文档第 1 节：本机有两份
平台代码，读错副本会得出完全相反的结论）。混在一起两边都读不清。

**一句话结论**（细节见那份文档）：对应不上，但缺的不是「几个接口」，是缺中间一整层
适配 —— 平台是内容侧（知识包 / 图谱 / 课件），本系统是运行时侧（会话 / 判星 / 报告），
两者互补而非重叠。
