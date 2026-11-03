# 当前学生端架构与业务逻辑

核查日期：2026-10-26。依据本仓库当前代码进行静态分析，不代表线上部署状态；本次未启动服务或执行真实模型、数据库和浏览器端到端验收。

## 1. 系统位置与职责

学生学习链路横跨三个服务：

| 服务 | 主要职责 | 核心入口 |
|---|---|---|
| platform | 登录、角色、选课、课程访问校验、发布内容查询、签发启动令牌、学情聚合 | `platform/frontend/src/routes/_layout/student.tsx`、`platform/backend/app/api/routes/student_bridge.py` |
| teacher_agent | 建设与发布课程，提供课堂播放器与媒体内容 | `/classroom-player/{classroomId}` |
| student_agent | 选择课时、课堂会话、知识点提取、教学对话、反馈与课后补完 | `student_agent/backend/main.py` |

三个服务通过统一网关访问，平台 API 使用 `/api/v1/*`，学生 API 使用 `/api/session/*`，学生静态前端使用 `/app`。数据库为同一个 PostgreSQL，不同业务使用不同 schema。平台桥接层读取教师 schema，学生服务直接写 student schema；因此当前不是完全通过 API 隔离的数据架构。

## 2. 学生服务内部结构

```text
student_agent/
├─ frontend/                         Next.js / React，静态导出
│  └─ src/
│     ├─ components/StudentApp.js     页面状态、会话恢复、请求与交互主入口
│     ├─ components/LessonProgress.js 阶段进度
│     ├─ components/LessonFeedback.js 逐知识点反馈
│     └─ integration/platform-player-adapter.js
│                                    iframe 播放器与 postMessage 适配
├─ backend/main.py                   FastAPI API、会话、后台任务、阶段入口
├─ agent/
│  ├─ context.py                     当前课堂场景转成教学材料
│  ├─ knowledge.py                   模型提取知识点、原文证据校验
│  ├─ graph.py                       课堂 LangGraph
│  ├─ progression.py                 确定性的教学阶段与计数规则
│  ├─ prompts.py                     模型提示词
│  ├─ feedback.py                    依据评估记录汇总反馈
│  ├─ postclass.py                   课后 LangGraph 与补完队列
│  ├─ persistence.py                 业务记录与快照保存、恢复
│  └─ database.py                    PostgreSQL 读写
└─ apps/                             兼容部署入口，加载配置后转入新后端
```

Next.js 使用 `output: "export"`，构建产物为 `frontend/out`，由 FastAPI 挂载。运行时页面由 React 本地状态切换；课堂对话通过普通 HTTP 请求获取完整结果，当前主链没有 SSE/WebSocket 流式回复。视频阶段知识点仍在准备时，每两秒轮询状态。

当前是围绕一个 AI 导师组织的两个工作流图：课堂图和课后图。代码没有展示多 Agent 自主协作，也没有以向量检索/RAG 为主的教学链路。

## 3. 进入课程与课时隔离

1. 学生登录平台，用选课码加入课程。
2. 学生首页请求已选课程和发布内容；点击进入学习。
3. 平台检查课程访问资格、选课关系与发布状态，签发短期 HMAC 启动令牌。
4. 浏览器跳转 `/app?launch_token=...`。
5. 学生后端请求平台 `learning-context`，首次只取得课时目录摘要。
6. 点击开始某课时，`begin/{lesson_id}` 再请求该课时的完整上下文。
7. 校验学生、课程、发布 ID、版本和所选课时一致，绑定课堂；缺少有效播放器时无法开始此主流程。

课时级上下文包含当前课堂场景文字、讲解动作、播放器地址等；其他课时的正文不进入本次教学会话。平台仍可能返回当前课时知识点文件解析出的 rubric，但当前学生 Agent 的提取链主要读取课堂画面文字与旁白，不消费该 rubric 作为教学知识点清单。

## 4. 视频与知识点准备

开始课堂后先保存 `phase=video`、`preparation=pending` 和材料，随后使用 FastAPI BackgroundTasks 调用模型整理知识点。模型处理过程不占用课堂锁，播放器可同时运行。

这里的“视频”实际复用教师端场景播放器，包含课件页面、讲解和媒体。学生 Agent 不直接识别视频像素或音轨，而是读取场景已有的画面文本与 speech 动作文本。

提取结果包括知识点名称及引用原文。代码检查引用场景有效、引用能在原文定位、知识点名称出现在证据中、证据具有最低长度，最终描述保存原文引用。它保证可追溯性，但不等于自动证明语义完整或教学质量。

全部候选失败时准备报错，可重试；部分候选有效时保留有效结果并标记 partial。服务读取 pending 会话时会重新调度准备任务；这依赖先恢复会话，并非独立持久任务队列。

播放器结束事件仅更新页面提示。进入讨论由按钮触发，未以 `videoEnded` 强制拦截，知识点准备完成即可进入。

## 5. 两层状态

外层服务管理课堂生命周期：`idle → video → discussion → done`。

内层 Agent 在 discussion 中推进：`recall → reinforce（按需）→ discuss（有合格点时）→ wrapup`。

前端还存在 loading、auth、lessons、lesson、replay、postclass 等显示状态。特别是回看和课后对话，通常仅切换前端视图，后端仍保持 `phase=done`。课后教学子阶段由 `postclassStage=remediation/open` 表示。

## 6. 课堂教学规则

每次学生发言执行：`evaluate → route → respond`。

- evaluate：模型结合当前知识点及近期对话，判断意图和回答结果。
- route：`progression.py` 根据规则更新计数、掌握状态、当前知识点和阶段。
- respond：模型按更新后的阶段与策略生成提示、纠错或下一题。

结果主要为 mastered、partial、misconception、unanswered；无有效判断时可记录 unclear。阶段推进由代码决定，语义判断仍依赖模型。模型调用失败时不会提交本轮对话及计数。

| 阶段 | 规则 |
|---|---|
| 初始复述 recall | 逐知识点处理，每点默认最多 8 轮；掌握提前推进，否则到上限留待加强 |
| 加强复述 reinforce | 首轮未掌握及首轮第 6–8 轮才掌握的知识点进入；每点默认最多 4 轮；后期掌握点仍需独立确认 |
| 深入讨论 discuss | 只选合格的已掌握点，每点一个应用问题；答对才推进，求助或答错围绕当前题继续，没有相同的固定轮次上限 |
| 课堂总结 wrapup | 所有合格点讨论完成，或没有合格点时进入；停止课堂发言，等待结束并生成反馈 |

首轮和加强上限可配置，取值范围 1–20，保存进会话。学生求助或表示不会也计入复述轮次。加强后仍未掌握的点排除在课堂深入讨论之外。学生可在讨论期间主动提前结束，系统记录结束阶段与未完成内容。

概念复述掌握与应用讨论结果分别保存；讨论答错不会直接清除概念已掌握结果。

## 7. 反馈与课后业务

结束后 `feedback.py` 依据实际评估记录汇总逐知识点反馈，包含掌握类别、首轮/加强/课后次数、判断依据、讨论结果及建议。它不是再次调用模型随意生成分数。

课后进入另一张 LangGraph。按知识点顺序判断待办类型：概念未掌握 → 首轮后期掌握但未加强确认 → 应完成但尚未答对的讨论题。当前知识点任务完成后继续后续任务，全部待办完成才开放自由提问。

课后独立讲清的概念标记为“课后补完”，反馈持续更新；课堂结束时的原反馈保留为 classroomFeedback。回看播放器地址缺失时可以单独请求 playback，不重启课堂或清空反馈。

## 8. 数据与恢复

| 数据位置 | 保存内容 |
|---|---|
| 服务进程内 `sessions` 字典 | 当前会话与线程锁 |
| 浏览器 localStorage | 按学生、课程、课时保存的签名会话快照、会话号与入口令牌 |
| student.student_sessions | 学生、课程、发布版本、课堂及起止状态 |
| student.student_messages | 有序对话消息与阶段 |
| student.knowledge_mastery | 跨会话掌握度，保留较高历史星级 |
| student.learning_events | Agent 快照、最终反馈与课堂原始反馈 |

默认 `STUDENT_FRESH_SESSION_MODE=1`：依然写数据库，但恢复优先采用当前浏览器签名快照，不默认读取数据库旧会话。新无痕窗口或另一设备不会自动恢复原学习过程。可显式关闭该模式启用数据库恢复。

前台没有使用旧版完整星级流程；持久化层仍将掌握、部分理解、误区分别映射到 4、2、1 星供旧数据结构兼容。本次课反馈读取本次实际评估，不使用历史最高星级替代本次结果。

commit 先写数据库再更新内存；失败返回错误。完成时反馈、最终快照、结束标记在一个事务提交，但此前会话、消息、掌握度分别写入，不是整轮单事务。

## 9. 当前架构边界

- 新学生端没有调用平台 `/internal/student/learning-progress` 的代码。平台虽有聚合与向教师端推送接口，当前不能据此宣称已完成实时学情推送。
- 平台课程 percent 按学习会话涉及的不同 classroom 数除以发布课堂工件数计算，更接近触达进度；不能直接解读为严格完成率或掌握率。
- 会话缓存与准备任务去重都在单进程内，扩展多 worker/多实例时需重新设计共享状态和任务调度。
- StudentApp.js 集中了页面与恢复逻辑，backend/main.py 集中了会话与平台交互；业务模块已有拆分，但这两个入口仍较重。
- 当前主链要求已发布课堂播放器；全班讨论、完整纯文本授课、课程级检索和跨设备自动续学不应算作已完成能力。
- `docs/student-runtime-mechanism.md` 与 `platform/docs/student-agent-integration.md` 包含旧 orchestrator、legacy、计时与评星机制，阅读时应以本说明所对应的当前源码为准。
