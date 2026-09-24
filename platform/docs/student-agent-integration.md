# 学生 Agent 正式接入审计与实施清单（student-agent-integration）

任务来源：2026-09-23 学生 Agent 正式接入任务书。本文是第一节"先审计"的交付物，
全部结论来自对三个仓库的实际代码阅读与运行验证，不基于假设。

## 1. 学生前端四视图真实调用链

前端形态：Next.js 静态导出挂 `/app`（`apps/static/app`），业务逻辑在
`frontend/src/legacy/*.js`（ES module），入口组件 `frontend/src/components/StudentApp.js`。

```
StudentApp.js（入口）
  ├─ 读 URL ?launch_token= → window.__studentLaunchToken（并 history.replaceState 从地址栏剥离）✅已接线
  └─ 动态 import legacy/app.js → 渲染静态骨架

视图流（app.js hash 路由，VIEWS 表 98-102 行）：
  #/            课程列表 view-courses   ← renderCourses() ← api.fetchStudentCourses()【写死】
  #/weeks/:c    周次列表 view-weeks     ← renderWeeks(course) ← course.lessons【随列表一起写死】
  #/class/:c/:l 课堂 view-class         ← api.fetchLesson(lessonId)【写死】→ startSession(带launch_token)
                                          → begin → 2 秒轮询 fetchSessionState/fetchSessionMessages
                                          → media_done / message → 下课
  #/review/:c/:l 课后 view-review       ← fetchLessonStars / fetchLessonReport(sessionId)
```

关键事实：`stage-class.js` 每 2 秒轮询 `/api/session/{sid}/messages?since=N`；视频区调
`StudentAgentVideoPlayer.mount(container, context)`，未注册 adapter 时显示"视频播放器待接入"
占位 + "跳过视频"按钮（直接触发 notifyVideoEnd）。

## 2. FastAPI 会话生命周期（apps/server.py）

```
POST /api/session/start      建会话（幂等）。body: session_id?/student_id?/lesson_id?/time_scale?/launch_token?
                             launch_token → platform_adapter.verify → 身份/课程/课堂/发布版本写入
                             state["platform"] 并随 _persist 落盘【已接线】；无 token 时 student_id
                             默认 "student-001"（弱身份，仅限 demo）
POST /api/session/{sid}/begin      起课铃：orchestrator.load_plan() 读 lesson-data/lesson-plan.json
                                   【固定路径，单课】→ 开场白 → 第一环节 + 心跳线程计时
POST /api/session/{sid}/media/done 播放完成：external_event=media_done → 推进素材游标
POST /api/session/{sid}/stage/next 下一环节（无条件切幕）
POST /api/session/{sid}/message    学生发言：编排一轮 LLM 反馈 + judge_mastery 判星
GET  /api/session/{sid}/state      状态查询（phase/计时/游标/stars/available_actions）
GET  /api/session/{sid}/messages   消息增量轮询（since=seq）
GET  /api/session/{sid}/stars|export  掌握度/课后报告
DELETE /api/session/{sid}          停课
```

状态机（orchestrator/agent.py，11 节点 LangGraph）：teach（video 模式静默等 media_done）→
复述（问答判星）→ 探究 → 下课总结。判定 `judge_mastery` 用 `EVIDENCE_GROUPS` 硬编码关键词
（agent.py:176-200，仅覆盖"处理机调度"KP-001..006）。

## 3. 写死数据/路径/规则清单（本次要替换的全部）

| 位置 | 写死内容 |
|---|---|
| `frontend/src/legacy/api.js:60-135` | `LESSON` 整对象（操作系统/处理机调度/6 段素材/起止秒数）、`LESSON_ID` |
| `frontend/src/legacy/api.js:89-109` | `fetchStudentCourses()` 返回单课写死数组（注释明示"届时把这个函数换成请求"） |
| `frontend/src/legacy/api.js:111-116` | `fetchLesson()` 只认 LESSON_ID |
| `orchestrator/agent.py:432` | `load_plan()` 固定读 `ROOT/lesson-data/lesson-plan.json` |
| `orchestrator/agent.py:176-200` | `EVIDENCE_GROUPS` 判星关键词（仅一门课） |
| `orchestrator/agent.py` KNOWLEDGE-BASE/`_hint()` | 处理机调度课程的知识库与提示 |
| `apps/server.py` StartIn 默认值 | `student_id="student-001"`、`lesson_id="ch3-process-scheduling"` |
| runtime 存储路径 | `runtime/sessions|students|data`（无数据库） |

## 4. launch_token 现状（已接线部分）

- 签发：平台 `student_bridge.open_student_workspace` → HMAC-SHA256（`STUDENT_SERVICE_KEY`），
  10 分钟有效，payload {uid,cid,rid,pub,exp,nonce}；
- 验证：学生 Agent `apps/platform_adapter.py::verify_launch_token`（签名+有效期+必填字段）；
- 持久化：start 后 `state["platform"]` = {userId,courseId,classroomId,publicationId,
  publicationVersion,launchedAt} 随会话 JSON 落盘（版本锁定已具备雏形）；
- 使用位置：仅 `/api/session/start`；authorize 端点（平台侧）已有但学生 Agent 尚未按请求调用。

## 5. video-player adapter 契约

`frontend/src/legacy/video-player.js`：
- `StudentAgentVideoPlayer.mount(container, context)`；未注册 adapter → 占位 UI；
- `StudentAgentVideoPlayerBridge.register(adapter)`：业务方播放器实现
  `{mount(container, options)}`，播放完必须回调 `options.onEnded()`；
- 当前唯一消费者 `stage-class.js:99-141`（`video:null` 硬传）。跳过按钮直接 `notifyVideoEnd()`。

## 6. 教师端发布数据结构（实测 shape）

- **知识包**（`teacher.mentra_knowledge_packages.payload`，status=published）：
  `{id, courseId, teacherId, version, status, createdAt, publishedAt,
    entries:[{id,title,content,courseId,citations:[{page,materialId,sourceName,sourceSha256}],approvedAt}]}`；
  心理健康课 v2 = 1 条 entry（测试课件文本 + 引用）。
- **课堂**（`teacher.mentra_classrooms`）：`stage{id,name}` + `scenes:[{id,type:'slide',order,title,
  actions:[{id,type:'speech'|'spotlight',text?,elementId?}],content:{canvas:{elements:[…]}}}]`；
  sandplay-e2e-v1 = 1 个 scene，actions 含 speech 讲稿（心理沙盘导入词）。
- **播放器**：教师服务内页面路由 `/classroom-player/{classroomId}`（= `/classroom/{id}` 别名，
  同一组件，非独立服务）；数据 API `GET /api/classroom?id=`（经平台 authorize，**当前仅教师角色
  可过**——学生播放授权是本次第六节工作）；媒体 `/api/classroom-media/{cid}/…`。
- **知识图谱**（判星依据的原料）：`mentra_course_graph_{versions,nodes,edges,evidence}`；
  心理健康课图谱 v1 在 review 状态（未发布——评估契约需按"无规则→通用语义评价"处理）。

## 7. 修改文件清单

### 新增独立模块（学生 Agent）
| 文件 | 职责 |
|---|---|
| `apps/integration/__init__.py` | 适配层包 |
| `apps/integration/config.py` | 环境变量集中校验（PLATFORM_AUTH_URL/STUDENT_SERVICE_KEY/STUDENT_DB_URL/STUDENT_DEMO_MODE），正式模式缺失 fail-closed |
| `apps/integration/platform_client.py` | 平台内部接口调用（X-Student-Service-Key、超时、401/403/404/409/503 映射、有限重试、不记密钥） |
| `apps/integration/launch_context.py` | launch_token 解析/生命周期（现有 apps/platform_adapter.py 升级并入） |
| `apps/integration/course_adapter.py` | CourseLearningContext → 内部课程模型（knowledgePackage→教学上下文、scenes→segments、版本锁定） |
| `apps/integration/evaluation.py` | 课程级评估契约（KP/预期概念/误区/完成规则；无规则→通用语义评价并标记默认） |
| `apps/integration/player_bridge.py` | 播放器事件协议（PLAYER_READY/SCENE_STARTED/SCENE_COMPLETED/PLAYBACK_ENDED/PLAYER_ERROR）、scene↔segment 映射、幂等 |
| `apps/integration/persistence.py` | student schema 读写（会话/消息/事件/进度/掌握度/报告），事务+幂等键 |
| `apps/integration/models.py` | 稳定领域模型（CourseLearningContext/Lesson/Segment，Pydantic） |
| `apps/demo/` | 写死课程数据迁移至此（仅 STUDENT_DEMO_MODE=true 可用） |
| `tests/` | 契约样本 + adapter 单测（launch/context 转换/事件幂等） |

### 新增/修改（平台）
| 文件 | 类型 |
|---|---|
| `student_bridge.py` 新增 `POST /internal/student/learning-context` | 独立端点（服务密钥+launch_token→版本化学习上下文，只返回 published） |
| `student_bridge.py` 新增播放授权签发（短期、限定 cid 的 playback token） | 第六节 |
| `teacher_bridge.py` authorize 新增学生播放路径（验证 playback token） | 第六节（教师端唯一挂钩，若与 PPT 更新冲突则延后重放） |
| `app/alembic/versions/final04_student_schema.py` | student schema 7 张表 DDL + student 角色 + DML 授权 |
| `tests/api/routes/test_student_bridge.py` 扩展 | learning-context/播放授权测试 |

### 最小业务挂钩（学生 Agent，逐条登记进 PLATFORM-INTEGRATION.md）
1. `apps/server.py` `/start`：launch_context 服务化调用（替换现有内联 verify）；
2. `orchestrator/agent.py` `load_plan()`：改调 course_adapter（按会话上下文，保留 demo 分支）；
3. `orchestrator/agent.py` `judge_mastery`：读 evaluation 契约（替换 EVIDENCE_GROUPS 直用）；
4. `frontend/src/components/StudentApp.js`：有 token 时跳过课程列表直进课堂视图；
5. `frontend/src/legacy/api.js`：fetchStudentCourses/fetchLesson 走上下文（demo 隔离）；
6. `frontend/src/legacy/stage-class.js`：视频区挂 player_bridge（iframe）。

### 禁止修改
- 教师端课件生成/播放器业务文件（他人正在改 PPT）；教师端仅允许 authorize 挂钩。
- 学生 Agent 状态机主体（除上述 3 个挂钩点）；上游测试夹具。

## 8. 实施顺序与提交划分

1. `student: add isolated platform integration adapters`（第四节模块+契约样本+单测）
2. `platform: learning-context service API`（第三节+测试）
3. `student: connect launch flow with minimal hooks`（含第二节入口归位）
4. `student: replace static course data with published context`（含第五节评估契约）
5. `student: add player event bridge`（第六节学生侧+平台授权；教师端挂钩视 PPT 冲突决定）
6. `student: persist learning state in student schema`（第七节+平台 final04 迁移）
7. `docs: record student Agent porting guide`（PLATFORM-INTEGRATION.md 全面更新）
8. 端到端验收（第八节清单）+ integration-log 登记

## 9. 已确认的测试基线

- 心理健康课 `8215ad2e-6d1f-411e-9290-eb288cfdbde0`：5 名选课学生（含 3 名真实），
  知识包 v2 published，课堂 `sandplay-e2e-v1` 已激活（CLS-A-c82g6JK4y3HF）；
- 历史源数据（旧课 T4aH3Es5zTcU、课堂 25Irw1T3AH）不动；
- 平台侧现有 175 passed 基线；学生 Agent smoke stages 通过基线。
