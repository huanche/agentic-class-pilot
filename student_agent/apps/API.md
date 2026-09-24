# 会话层 API · 前端对接文档

给做前端的同学：后端只有一组 HTTP 接口，全部在本机服务上（默认 `http://127.0.0.1:8000`，
局域网部署时换成老师机器的 IP）。**不需要 WebSocket**，轮询即可。
JSON 一律 UTF-8。

> 自己动手试：`python apps/start.py` 起服务，然后照下面的 curl 敲一遍。

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

无条件切到下一环节（复述 → 深度探究 → 课堂讨论[若启用] → 下课），
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

### 9. 课堂星级（按知识点，带中文标题）

```bash
curl http://127.0.0.1:8000/api/session/class-1/stars
```

```json
{ "knowledge_points": [
    { "kp_id": "KP-002", "title": "三级调度", "stars": 3, "status": "理解中" }
] }
```

形状与 `/export` 里的 `knowledge_points` 一致。**专门给上课时轮询用的**：
`/state` 的 `stars` 是 `{"KP-001": 3}` 这种裸 map，只有内部编号，
而 `MASTERY-STAR-RULES.md` 要求「不能把 KP-004 这类内部编号说给学生听」——
这里有 `kp_title()` 换好的中文标题。

### 10. 学情导出 / 停课

```bash
curl -o report.md http://127.0.0.1:8000/api/session/class-1/export?fmt=md    # 或 fmt=json
curl -X DELETE http://127.0.0.1:8000/api/session/class-1                      # 停课
```

`export?fmt=json` 是**课后学习报告**的数据源。注意它跟其它接口不一样：
**没有 `{ ok }` 信封**，直接返回整个对象，而且响应头带 `Content-Disposition: attachment`
（按「下载」设计的，浏览器 `fetch` 仍能读到 body）。

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
