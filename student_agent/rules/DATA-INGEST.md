# DATA-INGEST：数据接入与整理规则

本文件是「课程大纲 + 字幕 → 整理 → 落盘」这条数据管线的**唯一权威规则**。
数据从数据库（或临时数据源）读取，经 `ingest/` 模块清洗后，落到下面的规定位置。

---

## 1. 数据源

接入点抽象在 `ingest/datasource.py` 的 `DataSource` 类，只要求实现两个方法：

| 方法 | 返回 | 说明 |
| --- | --- | --- |
| `fetch_syllabus(course_id, lesson_id)` | `str \| None` | 原始课程大纲（脏数据） |
| `fetch_transcript(course_id, lesson_id)` | `str \| None` | 原始字幕（脏数据） |

当前实现用 `FileDataSource`（`ingest/sample/` 样例脏数据）。数据库数据源已撤；
如需接回数据库，再新增一个 `DataSource` 实现即可，清洗与落盘逻辑不动。

---

## 2. 四样产物与落点

整理产物**四样**，一一对应落点：

| 产物 | 来源 | 落点 |
| --- | --- | --- |
| **知识点** | 大纲 | ① 更新 `rules/KNOWLEDGE-BASE.md`（合并）；② `lesson-data/<course>/<lesson>/知识点.md`（一节课一个） |
| **课程目标** | 大纲 | `lesson-data/<course>/<lesson>/本节课目标.md` |
| **完整字幕** | 字幕 | `lesson-data/<course>/<lesson>/字幕.md` |
| **课时计划 lesson-plan** | 大纲 + 视频时长 | `lesson-data/<course>/<lesson>/lesson-plan.json` |

> 字幕**保留完整、不简化**：只去掉时间轴、序号、HTML 标签等噪音，正文一字不改。

---

## 3. 目录结构约定

`lesson-data/` 下按**课程 → 课时**两级组织，`course` / `lesson` 用现有的
`course_id` / `lesson_id`：

```
lesson-data/
├── <course_id>/
│   └── <lesson_id>/
│       ├── 知识点.md
│       ├── 本节课目标.md
│       ├── 字幕.md
│       └── lesson-plan.json
```

`lesson-plan.json` 是编排器要读的**课时定义**（阶段 + 时长）。编排器经
`orchestrator/agent.py:load_lesson` 的扫描兜底，从 `lesson-data/<course>/<lesson>/lesson-plan.json`
读它。旧的顶层 `lesson-data/lesson-plan.json` + `segments/` 保留兼容（旧版单课时）。

**创建课程时**用 `ingest/run.py --scaffold` 一次性建好这套目录 + 四个占位文件
（含默认 lesson-plan），之后整理出来的数据就知道往哪放。

`course_id` / `lesson_id` 走与 `orchestrator/agent.safe_lesson_id()` 相同的白名单校验
（字母数字与 `. _ -`、字母数字开头、≤64 字符、排除 Windows 保留设备名）。

---

## 4. 文件格式

### 4.1 知识点.md（字段名与 `rules/KNOWLEDGE-BASE.md` 完全一致）

```markdown
## KP-001 调度是什么
- 定义: ...
- 检测问题: ...
- 掌握表现: ...
- 为什么这样设计: 
- 如何实现: 
- 解决什么实际问题: 
- 关联学科: 
```

> 字段名刻意一致，保证未来能被 `agent.py` 的 `_parse_kb_questions()` / `_KP_TITLES`
> 正则直接复用解析。探究四字段（为什么/如何/用在哪/关联学科）可留空。

### 4.2 本节课目标.md（对齐 `runtime/TMISSION.md` 的「全班共同目标」）

```markdown
# 本节课目标
- 目标 1
- 目标 2
```

### 4.3 字幕.md

```markdown
# 字幕

（完整干净字幕正文，可保留时间轴）
```

### 4.4 lesson-plan.json（编排器课时定义，schema 与旧 `lesson-plan.json` 一致）

```json
{
  "lesson_id": "ch3-process-scheduling",
  "lesson_title": "第3章 处理机调度",
  "course_id": "operating-systems",
  "course": "操作系统",
  "total_minutes": 40,
  "stages": [
    {"id": "guided_learning", "enabled": true, "delivery": "video", "minutes": 0, "advance_when": "either"},
    {"id": "recap_discussion", "enabled": true, "minutes": 14, "advance_when": "either"},
    {"id": "deep_inquiry", "enabled": true, "minutes": 13, "advance_when": "either"},
    {"id": "class_discussion", "enabled": true, "minutes": 13, "advance_when": "budget"}
  ],
  "segments": [],
  "advance_policy": {
    "on_budget_exhausted": "wrap_up",
    "on_evidence_reached": "advance",
    "min_stage_minutes": 2,
    "max_stage_overrun_minutes": 3
  }
}
```

> `guided_learning` 是视频阶段（`delivery: "video"`），`minutes` 在视频时长未定时为 0（占位）。

---

## 5. 课时计划（lesson-plan）生成规则

由 `ingest/plan.py:build_plan` 生成，核心规则：

1. **总时长**：`extract.extract_duration` 从大纲抽「数字 + 分钟/min」（如“45 分钟”）；
   **读不到 → 默认 40 分钟**。
2. **视频时长**：暂定，先当显式输入（`--video-minutes`，默认 0 = 占位）。等视频接入后再填。
3. **剩余时长** = 总时长 − 视频时长（视频播放完之后剩下的，分给非视频阶段）。
4. **阶段分配**：
   - 优先走**规划 AI**（环境变量 `PLANNER_LLM_BASE_URL / PLANNER_LLM_API_KEY / PLANNER_LLM_MODEL`，
     OpenAI 兼容端点），由它决定启用哪些非视频阶段（要不要复述 `recap_discussion` 等）以及各阶段分钟。
   - 没配 AI 或调用失败 → **确定性规则**兜底：按「复述 → 探究 → 讨论」优先级贪心启用，
     剩余时长均分，余数往前补。
   - **每个非视频阶段 ≥ 2 分钟**（`advance_policy.min_stage_minutes = 2`）。
5. `segments`（视频段落）**暂留空**，等视频分段信息到位后再填。

---

## 6. 清洗规则（`ingest/extract.py`）

- **字幕**（`clean_transcript`）：剥时间轴行（`00:12:30,000 --> …`）、序号行、
  HTML 标签、`WEBVTT`/`NOTE` 等头部噪音，合并为完整干净文本。**不摘要、不删正文。**
- **知识点**（`extract_knowledge_points`）：按 `## KP-xxx 标题` 锚点分段，
  逐段抽 `- 字段: 值`。
- **课程目标**（`extract_goals`）：按「教学目标 / 课程目标 / 学习目标 / 本节课目标」
  锚点，抽其后的列表条目。

> 假设大纲是带层级标题的结构化文本（docx/大纲导出）。若实际是自由文本，
> 提取函数预留 LLM 抽取扩展点（离线、不影响上课）。

---

## 7. 运行入口

```bash
python ingest/run.py --course operating-systems --lesson ch3-process-scheduling   # 读源 → 整理 → 规划 → 落盘
python ingest/run.py --course X --lesson Y --scaffold                             # 只建骨架 + 默认 lesson-plan
python ingest/run.py --course X --lesson Y --video-minutes 22                     # 指定视频时长（分钟）
```

- `--video-minutes`：视频时长（分钟），默认 0（暂定占位）。
- 规划 AI 用 `PLANNER_LLM_*` 三个环境变量（OpenAI 兼容 `/chat/completions` 端点），
  与课中教学 AI 的 `AGENT_LLM_*` 分开配置（可用更便宜/快的模型）。
