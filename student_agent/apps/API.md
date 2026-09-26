# 会话层 API · 前端对接文档

给做前端的同学：后端只有一组 HTTP 接口，全部在本机服务上（默认 `http://127.0.0.1:8000`，
局域网部署时换成老师机器的 IP）。**不需要 WebSocket**，轮询即可。
JSON 一律 UTF-8。

> 自己动手试：`python apps/start.py` 起服务，然后照下面的 curl 敲一遍。
>
> **要接 SaaS 底座或教师端**，看 [API-SAAS.md](API-SAAS.md) —— 那份讲跨系统
> 怎么对接、谁调谁、有哪些缺口；本文只讲接口本身。
>
> **要对 SZU-AgentEduPlatform 那套平台**，看
> [PLATFORM-INTEGRATION.md](PLATFORM-INTEGRATION.md) —— 那份是逐行实测，
> 结论是两边对不上、缺中间一层适配。

## 一节课的完整时序

```
学生打开页面
   │
   ▼
① POST /api/session/start          进教室（此时不上课，状态 = idle）
   │                               页面显示「等老师开始上课」，输入框禁用
   ▼
② 老师按「开始上课」
   POST /api/session/{sid}/begin   ★ 起课铃：开场白 + 开始计时
   │
   ▼   ┌────────────── 讲解阶段（guided_learning）──────────────┐
   │   │ 老师这边放讲解视频（视频由前端自己托管播放）             │
   │   │                                                        │
   │   │ ★ AI 全程静默：没有讲解词、不会打扰视频                 │
   │   │ ★ 视频时间照常计入课堂时长（进度条会走）                 │
   │   │ ★ 讲解阶段不会被时间预算切走——视频多长都等它放完        │
   │   │                                                        │
   │   │ 全片播完 ▶ POST /api/session/{sid}/media/done（一次）  │
   │   │            → 自动进入复述阶段 + 抛出第一问              │
   │   └────────────────────────────────────────────────────────┘
   ▼
④ 复述 / 深度探究：学生打字 → POST message，AI 反馈 + 记星级
   │   （这两个阶段老师随时可以按「下一环节」跳走）
   ▼
⑤ POST /api/session/{sid}/stage/next   ★ 下一环节，无条件切幕
   │
   ▼
⑥ 状态 status 变成 ended → 显示下课总结，学情按钮可导出
```

核心一句话：**三个按钮（开始上课 / 视频播完 / 下一环节）+ 一个输入框**，
讲解阶段的内容全在视频里（本课配置为 `delivery: "video"`，见 lesson-plan.json）。

## 通用约定

- `available_actions`：每个写接口的返回和 `/state` 里都带，是一个数组，
  取值 `begin` / `message` / `media_done` / `next_stage` / `stop` / `export`。
  **按钮能不能按，照它渲染，别自己猜**。
- `status`：`idle`（进教室未上课）→ `running`（上课中）→ `ended`（下课）。
- 错误：HTTP 404 会话不存在；409 状态不允许（如没上课就发消息）；400 参数错。响应体是 `{"detail": "..."}`。
- 消息展示：心跳轮询 `GET /messages?since=N`（N 是上次拿到的 total），
  AI 主动说的话（讲新段、抛题、切幕开场白）都从这条增量接口里出来。

## 接口明细

### 1. 进教室

```bash
curl -X POST http://127.0.0.1:8000/api/session/start \
  -H "Content-Type: application/json" \
  -d '{"session_id": "class-1", "student_id": "student-001"}'
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| session_id | str? | 不传则后端生成。**一个学生一节课一个 id**，刷新页面要复用同一个 |
| student_id | str? | 默认 student-001 |
| time_scale | float? | >1 压缩课时（演示用 12 = 45 分钟压成 4 分钟），正式上课别传 |

返回：`{"session_id", "status": "idle", "phase", "available_actions": ["begin"], "reply_text": ""}`

幂等：重复调不会重新开课。

### 2. ★ 开始上课（起课铃）

```bash
curl -X POST http://127.0.0.1:8000/api/session/class-1/begin
```

返回：`{"reply_text": "开场白…（可直接展示）", "phase", "phase_name", "status": "running", "available_actions": [...]}`

同一次会话只能 begin 一次，再来报 409。

### 3. ★ 视频播完

```bash
curl -X POST http://127.0.0.1:8000/api/session/class-1/media/done
```

**整段视频全片播完时报一次**（本课为视频讲解模式）。

后端行为：确认素材全部播完 → 自动切进复述阶段，
返回的 `reply_text` 是复述开场白 + 第一问（直接展示即可）。

返回：`{"reply_text", "phase", "phase_name", "status", "advance_reason", "available_actions"}`

### 4. ★ 下一环节

```bash
curl -X POST http://127.0.0.1:8000/api/session/class-1/stage/next
```

无条件切到下一环节（复述 → 深度探究 → 下课），
不管时间够不够、题答没答完——给老师掌控节奏用的。

返回：`{"reply_text"（新环节开场白+第一问）, "phase", "phase_name", "status", "available_actions"}`

### 5. 学生发言

```bash
curl -X POST http://127.0.0.1:8000/api/session/class-1/message \
  -H "Content-Type: application/json" \
  -d '{"text": "高级调度把作业调进内存，低级调度决定谁上 CPU"}'
```

返回：`{"reply_text"（AI 的反馈）, "phase", "phase_name", "status", "available_actions"}`

### 6. 统一事件入口（可选）

不想对接三个 URL 的话，只对接这一个也行：

```bash
curl -X POST http://127.0.0.1:8000/api/session/class-1/event \
  -H "Content-Type: application/json" \
  -d '{"type": "begin"}'           # begin / media_done / next_stage
```

返回同对应接口。

### 7. 状态（轮询用，2 秒一次足够）

```bash
curl http://127.0.0.1:8000/api/session/class-1/state
```

```json
{
  "status": "running",
  "phase": "guided_learning",
  "phase_name": "讲解阶段",
  "stage_elapsed_minutes": 3.2,
  "stage_budget_minutes": 22.0,
  "lesson_elapsed_minutes": 3.2,
  "total_minutes": 45,
  "current_question": null,          // 复述/探究阶段的当前问题，可直接展示
  "advance_reason": "…",
  "student_status": "active",
  "time_scale": 1.0,
  "stars": {"KP-001": 1, "KP-002": 2},
  "segment_cursor": 3,              // 讲解素材：当前第几段（0 起）
  "segment_total": 6,
  "played_media": [...],            // 已播完的素材
  "remaining_stages": ["recap_discussion", "deep_inquiry"],
  "next_stage": "recap_discussion",
  "available_actions": ["message", "media_done", "next_stage", "stop"]
}
```

进度条：`stage_elapsed_minutes / stage_budget_minutes`（本环节）、
`lesson_elapsed_minutes / total_minutes`（全课）。课没开始时计时全是 0。

### 8. 消息增量

```bash
curl "http://127.0.0.1:8000/api/session/class-1/messages?since=5"
```

```json
{"messages": [
   {"seq": 5, "role": "teacher", "text": "…", "at": "…", "phase": "…", "llm": true}
 ],
 "total": 6, "student_id": "student-001"}
```

`since` = 上次返回的 `total`。AI 主动说的话（心跳推进产生的）也在这条里出现，
**所以轮询这条就够把对话画完整**。

### 9. 学情导出 / 停课

```bash
curl -o report.md http://127.0.0.1:8000/api/session/class-1/export?fmt=md    # 或 fmt=json
curl -X DELETE http://127.0.0.1:8000/api/session/class-1                      # 停课
```

### 10. 老师上传课时定义

```bash
curl -X POST http://127.0.0.1:8000/api/teacher/lesson \
  -H 'Content-Type: application/json' -d @lesson.json
```

一次传完整的一节课：元数据 + `stages` + `segments` + `knowledge_points`。
落盘成 `lesson-data/lessons/<lesson_id>.json`，之后这节课就能像原来那节一样
出现在选课目录、能开课、能看课后报告。

```json
{
  "lesson_id": "ch4-deadlock",
  "lesson_title": "第4章 死锁",
  "course_id": "operating-systems",
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
     "定义": "……", "检测问题": "……", "掌握表现": "……",
     "为什么这样设计": "", "如何实现": "", "解决什么实际问题": "", "关联学科": ""}
  ],
  "segments": [
    {"id": "seg-401", "minutes": 20, "order": 1, "title": "……",
     "knowledge_point_ids": ["KP-401"], "knowledge_points": ["死锁"],
     "summary": "……", "content": "……"}
  ]
}
```

约束：`stages[].id` 只能是 `guided_learning` / `recap_discussion` /
`deep_inquiry`；`segments[].knowledge_point_ids` 必须指向
本课已声明的 `kp_id`；`advance_policy` 与 `segments[].order` 可省，省略时用默认值。

回读确认存进去了什么：

```bash
curl http://127.0.0.1:8000/api/teacher/lesson/ch4-deadlock
```

返回 `{ok, lesson, source, problems}`；`problems` 非空表示这份定义开课时会失败。

**错误码**：`lesson_id` 非法（`../evil`、`a/b`、`CON` 这类）→ 400；
定义校验不过（阶段 / 段落 / 知识点 / `advance_policy`）→ 422，
`detail` 里是中文问题清单。

**三个必须知道的点**：

1. **校验用的就是开课时那一套 `validate_plan`** —— 这里过了，开课就不会再
   因为计划本身失败。反过来，绕过接口手改文件可能让 `/begin` 报「开课校验失败」。
2. **改完要新建会话才生效**。会话在 `/begin` 那一刻把课时定义冻进状态
   （老师不该在上课中途被抽掉进度），响应里的 `staleSessions` 会列出受影响的
   在跑会话。但老师传的**知识点正文**是每轮重读的，改错别字下一次心跳就生效。
3. **可以覆盖内置课时**。`ch3-process-scheduling` 是仓库自带的，走
   `lesson-data/lesson-plan.json`。用同一个 id 上传会生成
   `lesson-data/lessons/ch3-process-scheduling.json`，它**优先于**内置那份；
   删掉这个文件就恢复原样，内置文件本身全程不被改写。

老师传的知识点会进模型的备课材料（`assembled_prompt` 的 `[本课知识点]`），
但**讲什么、问什么仍由编排骨架决定**，模型只负责把话说准。
`assembled_prompt` 属于编排遥测，任何情况都不下发给学生端。

## 前端注意事项

1. **视频播放器完全归前端**：视频文件、播放、暂停、拖动都自己管；
   后端只收「全片播完了」这一个事实（`media/done`，播完调一次）。
   播放期间不用轮询等待讲解词——**视频模式下 AI 不会输出讲解词**。
2. **视频时间计入课堂**：begin 之后全课计时就开始走，
   `/state` 的 `lesson_elapsed_minutes` 会随播放增长（进度条正常画）。
   讲解阶段不会被时间预算自动切走，放心放完整段视频。
3. **别在 idle 态放开输入框**，学生发言会收 409。
4. `reply_text` 里可能带换行，用 `white-space: pre-wrap` 展示。
5. 页面参考实现在 `apps/static/index.html`（含三个按钮 + 输入框 + 进度条 + 2 秒轮询），
   可以直接拿去改。
6. 联调前先自己彩排一遍：`python apps/smoke_test.py stages`（用三个按钮走完整节课，
   不需要真实视频和时间）。
