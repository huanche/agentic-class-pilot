# 主动引导智能体

一个由**课程计划驱动、AI 自动推进**的课堂智能体。

> 本仓库是 `HELLO-APL/Dify-Classroom-Interactive-Agent` 的重构版。
> 旧仓库 `D:\project\Dify 课堂互动智能体` 保留不动，仅作参照。
>
> **主要变化**：移除学生标注与 n8n · 改为四阶段（可配置）编排模型 · 新增 LangGraph 编排结构 · 学生端统一并入 `frontend/`。

---

## 这是什么

学生端不是一个"学生问、AI 答"的聊天机器人，而是**一个按老师排好的课程计划自动推进的课堂**：

```
老师配置 lesson-plan.json  ──→  AI 每轮读计划 + 判证据 + 判耗时  ──→  自动切幕
（上几个阶段、每阶段多久）        （编排器 host_phase 状态机）          （把课上完）
```

**核心设计：** 提示词负责"怎么教"，数据负责"教什么、按什么顺序教、多久教完"。改课程结构不用改提示词。

> 本仓库现在包含智能体、FastAPI 会话层和 Next.js 学生端。所有阶段共用
> `POST /api/session/{sid}/message`，由后端 `host_phase` 决定当前教学行为。

---

## 目录结构

```
主动引导智能体/
├── rules/                       # 规则层（AI 每轮只读，老师维护）
│   ├── KNOWLEDGE-BASE.md        # 知识点目录（含 4 个探究字段）
│   ├── interaction/             # 课堂节奏规则、判星规则、各文件格式模板
│   │   ├── RECAP-GUIDE.md       #   ★ 复述引导：学生状态 → 引导策略（代码每轮读它）
│   │   ├── MASTERY-STAR-RULES.md   # 0-5 星唯一权威规则
│   │   └── *-FORMAT.md          #   七个运行时文件的字段模板
│
├── lesson-data/                 # 课程数据层（老师配置）
│   ├── lesson-plan.json         #   ★ 编排入口：阶段开关 + 时长预算 + 推进策略 + 时钟策略
│   └── segments/seg-XXX.json    #   课程片段（order 定顺序，绑定 KP）
│
├── stages/                      # 阶段内容层（可空壳，留空不影响运行）
│   ├── recap_discussion/        #   复述：prompt.md（问题/判分由知识点字段与通用规则提供）
│   └── deep_inquiry/            #   深挖：questions.md / rubric.md / prompt.md
│
├── runtime/                     # 运行时状态（每轮读写）
│   ├── DIALOGUE-LOG.md          #   ★ 会话控制 + 编排器字段
│   ├── TMISSION.md              #   老师目标、核心难点、易混淆点
│   ├── LESSON-CONTENT.md        #   本课内容（先修/新内容/任务/成功证据）
│   ├── SMISSION.md              #   学生个人目标
│   ├── NOTES.md                 #   工作观察与偏好
│   ├── GLOSSARY.md              #   已挣得的词汇
│   ├── LEARNING-RECORD.md       #   持久学习记录
│   └── data/                    #   掌握度与对话流水（json）
│       ├── mastery-state.json
│       ├── mastery-history.json
│       └── dialogue-log.json
│
├── apps/                        # 会话层：把编排器接进真实对话
│   ├── server.py                #   ★ FastAPI：开课 / 发言 / 心跳时钟 / 学情导出
│   ├── smoke_test.py            #   ★ 课前彩排脚本（不发言跑完一节课）
│   └── static/index.html        #     学生端页面（对话 + 阶段进度）
│
├── frontend/                    # Next.js 学生端；静态构建由 FastAPI 同源托管
│   ├── src/                     #   页面、课堂阶段与统一 API 适配层
│   └── out/                     #   npm run build 生成（不入库）
│
└── orchestrator/                # 编排器：规范 + 实现 + 演示
    ├── ORCHESTRATOR.md          #   ★ LangGraph 状态图、节点、条件边、调度约定（权威规范）
    ├── agent.py                 #   ★ 真实 LangGraph 实现（11 节点，可直接跑）
    ├── run_demo.py              #   ★ 模拟一节课并打印编排过程
    ├── demo-run.md              #     上面这个脚本的一次真实运行实录
    ├── graph_skeleton.py        #     骨架版（只看 LangGraph 怎么写，不跑）
    ├── HOW-IT-WORKS.md          #     自然语言讲运作过程
    ├── clock_reference.py       #     真实时钟与切幕判定的参考实现 + 回归测试
    └── MIGRATION.md             #     从旧仓库迁移的映射与变更记录
```

### 跑起来（真实 LangGraph）

```bash
# 依赖装在隔离 Python 环境里
pip install -r requirements.txt
python orchestrator/run_demo.py        # 模拟一节课（讲解 → 复述 → 探究 → 下课）
```

### 课堂里跑起来（一键）

**双击项目根目录的 `启动课堂.bat`** —— 起服务、自动开浏览器、打印局域网地址，就这样。

### 测试

```powershell
# 后端接口与阶段状态机
python -m unittest apps.test_api_integration -v

# 前端代码检查
npm run lint --prefix frontend

# 构建前端、启动真实后端，并用浏览器走完整课堂流程
npm run test:e2e --prefix frontend
```

端到端测试会实际点击课程、开始上课、结束视频、提交复述与深入思考，并断言课堂
正确走到结束页。

命令行等价物（可加参数）：

```bash
python apps/start.py                 # 默认 0.0.0.0:8000，自动开浏览器
python apps/start.py --scale 12      # 打开的页面带 12 倍速：45 分钟压成约 4 分钟
python apps/start.py --port 8080     # 换端口
python apps/start.py --no-browser    # 只起服务
```

启动后会打印两行地址：**本机上课**（老师自己）和 **手机/学生端**（局域网，让学生连这个）。结束按 `Ctrl+C`。

### 课堂怎么上（三个入口，同一套后端）

一节课的流程：**进教室（待机）→ 老师按「开始上课」→ 播放一整段讲解视频（AI 全程静默，
时间照常计入课堂）→ 视频全片播完、报告一次 → 复述/深度探究（学生打字答题）→
老师按「下一环节」一步步走 → 下课导出学情**。

> 讲解阶段的授课方式由 `lesson-plan.json` 里 guided_learning 的 `delivery` 决定：
> `video`（本课，整段视频替代讲解，AI 不出讲解词，视频再长也不会被时间预算切走）
> 或 `narration`（默认，AI 逐段讲解，适合没有视频的课）。

| 入口 | 命令 | 给谁用 |
| --- | --- | --- |
| 网页 | 浏览器打开 `http://127.0.0.1:8000/` | 老师/学生。页面自带「开始上课 / 视频播完 / 下一环节」三个按钮 |
| **命令行窗口** | `python apps/cli.py` | 不等前端时直接上课：`/begin` `/video` `/next` 是三个按钮，直接打字是学生发言 |
| HTTP API | 见 **`apps/API.md`** | 前端同学对接用：全部接口、字段、时序图、curl 示例 |

命令行窗口长这样：

```
[等待上课·uninitialized] > /begin
[上课中·讲解阶段] > /video
[上课中·讲解阶段] > （第 2 段讲解词）
[上课中·复述阶段] > 高级调度把作业调进内存……
[上课中·复述阶段] > （AI 反馈 + 星级）
[上课中·复述阶段] > /next
```

| 机制 | 说明 |
| --- | --- |
| **三个老师按钮** | `POST /begin`（起课铃）、`POST /media/done`（**整段视频全片播完报一次**：自动切进复述并抛出第一问）、`POST /stage/next`（下一环节：无条件切幕，不受时间/证据门槛限制）。 |
| **视频讲解模式** | 讲解阶段 AI 全程静默不出讲解词；视频时间照常计入课堂时长；讲解阶段只认「视频播完」或老师按钮，**时间预算不切幕**（视频多长都等它放完）。 |
| **待机态** | 学生进教室后课**不算开始**：不计时、不发消息（409）、心跳不推进。起课铃响了一切才开始。 |
| **心跳时钟** | 服务每 10 秒（`AGENT_TICK_SECONDS`）把时钟推一次，只在上课中推进。学生不打字时到点讲下一段、到点抛下一问、到点切幕；**没新内容就静默不开口**。 |
| **会话持久化** | 状态落在 `runtime/sessions/<sid>.json`，进程重启能续上（上课中的课会把心跳线程接回来）。 |
| **学情导出** | 课后 `GET /api/session/<sid>/export?fmt=md`（或 `fmt=json`），页面/CLI 的「学情」按钮就是它。 |

课前彩排（两种驱动方式各跑一遍）：

```bash
python apps/smoke_test.py stages           # ★ 用三个按钮走完整节课（不依赖真实时间）
python apps/smoke_test.py auto --scale 30  # 全程不发言不按钮，看心跳能不能自己上完
python apps/smoke_test.py chat             # 模拟学生答题，看反馈与判星
```

> ⚠ **上课前别让电脑休眠。** 时钟是真实的：休眠一晚唤醒后会发现课时一下跳出去，直接走到下课。

### 接真实大模型（可选）

`teach` 节点接任意 OpenAI 兼容端点。**不配也能跑完整节课**，只是老师的话是模板生成的。

```bash
cp .env.local.example .env.local    # 然后填入你的 Key（该文件已进 .gitignore）
python orchestrator/llm_probe.py    # 先单独验证端点通不通
python orchestrator/run_demo.py     # 再跑整节课
```

也可以直接用环境变量，不用建文件：

```bash
export AGENT_LLM_BASE_URL=https://api.deepseek.com/v1
export AGENT_LLM_API_KEY=sk-xxx
export AGENT_LLM_MODEL=deepseek-chat
```

> **模型只负责措辞，不负责编排。** `teach` 分两层：确定性骨架决定"讲哪段、问哪题"，
> 模型把指令润色成自然语言。所以模型挂了课照常上完，切幕与星级一字不差。
> 已验证：有/无 LLM 两种方式跑同一串时间戳，剔除老师说的话后 **51 行编排结果逐行相同**。
> 详见 `ORCHESTRATOR.md` 第 3.1 节。

演示输出会标出每轮回复的来源：`老师[AI  ]>` 是模型生成，`老师[脚本]>` 是降级文案。

---

## 四个阶段

| 阶段 | `host_phase` | 时间 | 干什么 | 星级影响 |
| --- | --- | --- | --- | --- |
| 开场 | `intro` | — | 交代目标与互动方式 | — |
| 引导学习 | `guided_learning` | 0-50% | 讲解 + 主动提问 | 1 星（已接触） |
| 复述与讨论 | `recap_discussion` | 50-70% | 学生复述，AI 补缺口 | 2-3 星 |
| 深层探究 | `deep_inquiry` | 70-100% | 追问为什么/如何/用在哪/跨学科 | 4 星 |
| 收尾 | `ending` | — | 总结 + 遗留问题 | — |

**阶段可自由启停**：`lesson-plan.json` 里 `enabled: false` 即可跳过。

---

## 老师配一门课：三步

> **现在有接口了**：`POST /api/teacher/lesson` 一次传完整的一节课
> （元数据 + 阶段 + 段落 + 知识点），落盘成 `lesson-data/lessons/<lesson_id>.json`，
> 不用再手工改三处文件；系统也不再只能跑一节课。契约见
> [apps/API.md 第 10 节](apps/API.md)，回读用 `GET /api/teacher/lesson/{id}`。
>
> 下面写的是直接改文件的老路子 —— 它仍然有效（`lesson-data/lesson-plan.json`
> 那一节原样保留），适合还没接接口时的本地调试。

### 1. 定阶段与时长

编辑 `lesson-data/lesson-plan.json`：

```json
{
  "lesson_id": "ch3-process-scheduling",
  "total_minutes": 45,
  "stages": [
    { "id": "guided_learning",  "enabled": true,  "minutes": 22, "advance_when": "either" },
    { "id": "recap_discussion", "enabled": true,  "minutes": 9,  "advance_when": "either" },
    { "id": "deep_inquiry",     "enabled": true,  "minutes": 7,  "advance_when": "either" }
  ]
}
```

| 字段 | 含义 |
| --- | --- |
| `enabled` | `false` → **整段跳过**（比如这门课不要某个环节） |
| `minutes` | 这一幕的**时长预算** |
| `advance_when` | `either`（证据达标或时间到）/ `evidence`（学透才走）/ `budget`（只看时间） |

### 1.1 时间怎么算（真实时钟）

编排器**用真实时间**推进，不看"聊了几轮"，也不靠 LLM 估算时长。每轮由会话层把当前时间戳（`now`）注入状态，编排器只做一件事：

```
stage_elapsed_minutes  = now - stage_started_at     # 本幕已花分钟
lesson_elapsed_minutes = now - lesson_started_at    # 本课已花分钟
```

到点（`minutes` 预算耗尽）就切下一幕。**编排器不管学生是否在场** —— 那是老师的事。

```json
"advance_policy": {
  "on_budget_exhausted": "wrap_up",       // 预算耗尽：wrap_up 收尾后切 / force_advance 立即切 / extend 允许延长
  "on_evidence_reached": "advance",       // 证据达标：切幕
  "min_stage_minutes": 2,                 // 最短幕时长，防止秒切
  "max_stage_overrun_minutes": 3          // extend 模式下最多超时多少
}
```

> 时间戳由会话层注入而非编排器自己取，是为了让切幕逻辑**可单测、可回放**。
> 参考实现与 11 条回归测试见 `orchestrator/clock_reference.py`。

### 2. 填课程内容

| 要写什么 | 写在哪 | 现状 |
| --- | --- | --- |
| 知识点 + 检测问题 + 4 个探究字段 | `rules/KNOWLEDGE-BASE.md` | 探究字段待填 |
| 老师目标、核心难点（检验问题）、易混淆点 | `runtime/TMISSION.md` | 内容已有 |
| 本课先修/新内容/任务/成功证据 | `runtime/LESSON-CONTENT.md` | 内容已有 |
| 每个片段讲什么 | `lesson-data/segments/seg-XXX.json` | 已有 |
| 各阶段的问题与评判标准 | `stages/<阶段>/questions.md` · `rubric.md`（复述阶段无此两项） | **暂不填（按需）** |

### 3. 交付给编排器

按 `orchestrator/ORCHESTRATOR.md` 实现状态图。老师侧无需理解节点连法 —— **规则与配置就是燃料**。

---

## 空壳也能跑

**关键约定**：阶段内容可以完全不写，编排器照常运行。

| 缺失 | 降级行为 |
| --- | --- |
| `stages/<id>/questions.md` 空 | 改用 `KNOWLEDGE-BASE.md` 的 `检测问题` |
| `stages/<id>/rubric.md` 空 | 只用 `MASTERY-STAR-RULES.md` 的通用标准 |
| `stages/<id>/prompt.md` 空 | 用内置默认提示词 |

> 复述阶段（`recap_discussion`）已删去 `questions.md` / `rubric.md`，只剩 `prompt.md`：
> 问题取 `TMISSION.md` 检验问题（空则回落 `KNOWLEDGE-BASE.md` 的 `检测问题`），
> 判分只用 `MASTERY-STAR-RULES.md` 通用标准。

所以**整条链路现在就是可运行的**，只是问法朴素。填上 `stages/` 后质量自然提升，不需要改代码。

---

## 已经移除的功能

| 移除项 | 说明 |
| --- | --- |
| **学生标注（class point）** | 标记点、`points/*.json`、`point_review` 幕、「继续」事件、标注接口 |
| **区分问题** | 该概念废弃。易混淆点只在 `TMISSION.md` 列名称 |
| 1 星"已标注" | 改为 **"已接触"**（AI 讲过即记，不再依赖标注） |
| `source: class_point` | 剩余来源：`dialogue` / `assessment` / `manual` |
| `lecturing` / `segment_summary` 幕 | 被四阶段模型取代 |
| **n8n 工作流** | 本仓库不再包含 `workflow/` 与 n8n 节点 |
| `LESSON-INTERACTION.md` | 改名为 `LESSON-CONTENT.md`（旧名与实际内容不符） |

---

## 关键文档

| 文档 | 内容 |
| --- | --- |
| `orchestrator/ORCHESTRATOR.md` | **编排器结构**：LangGraph 状态 schema、节点、条件边、文件调度、校验规则 |
| `orchestrator/MIGRATION.md` | 新旧路径映射与变更记录 |
| `rules/interaction/RECAP-GUIDE.md` | **复述引导（状态驱动）**：学生状态 → 策略 → 动作。改它就能改 AI 的复述引导，不用动代码 |
| `rules/interaction/MASTERY-STAR-RULES.md` | **0-5 星唯一权威规则** + 阶段快照机制 |
| `rules/interaction/DIALOGUE-LOG-FORMAT.md` | 会话状态字段（含编排器字段） |
| `rules/interaction/LESSON-CONTENT-FORMAT.md` | `LESSON-CONTENT` 与 `TMISSION` 的分工 |
| `stages/*/README.md` | 各阶段在干什么、没配置时怎么降级 |
| `apps/API.md` | **会话层接口**：一节课的完整时序、九个会话接口、老师上传课时定义（第 10 节） |
| `apps/API-SAAS.md` | **SaaS 底座 × 教师端对接**：双向调用关系、教师端两条接入路径、鉴权现状与缺口清单 |
| `apps/PLATFORM-INTEGRATION.md` | **平台对接分析**：SZU-AgentEduPlatform 接口的逐行实测、与学生端的字段映射、差在哪 |
| `frontend/docs/api/后端接口说明.md` | **学生端接口说明**：统一消息入口、控制与同步接口、课后报告契约 |

---

## 学生端：课后学习报告

课后页展示这节课的学习报告，三块内容：**知识点掌握**（0–5 星 + 状态）、
**各阶段表现**（阶段名 + 用时 + 目标计数）、**课后建议**（从知识点里挑 `stars <= 2` 的，
与后端 md 分支的「理解线」一致）。

只呈现学生自己的部分：教师侧的会话标识（`student_id` / `session_id`）、原始证据摘录
（`stage_snapshots[].evidence`）和编排遥测（`advance_reason`、`assembled_prompt`）都不下发到这一页。
星级以后端 `rules/interaction/MASTERY-STAR-RULES.md` 为准，前端不自己算一套。

数据来自 `GET /api/session/{sid}/export?fmt=json`（`apps/server.py` 的 `export()`，
与它自己 `fmt=md` 的「学情报告」是同一份数据）。**响应是裸 JSON，没有 `{ ok }` 信封**，
与本仓库其它接口不同。契约与对接注意点见
[学生端接口说明](frontend/docs/api/后端接口说明.md#课后学情报告学生版)。

---

## 已知缺口（待解决）

| 缺口 | 影响 | 优先级 |
| --- | --- | --- |
| **对话日志文件仍共享** | 掌握档案已按学生隔离（`runtime/students/<student_id>/`，2026-09-21 起），但 `runtime/DIALOGUE-LOG.md` 与 `data/dialogue.json` 仍是全课共享文件——多人同上时日志内容会混在一起，**不影响判定与星级**，只影响日志可读性 | 中 |
| **对话记忆窗口有限** | 长课程可能丢上下文 | 高 |
| **视频位置接口未打通** | `source.position` 是占位符 | 中 |
| **判星粒度未定** | 各阶段星级的精确判定标准待明确 | 中 |
| **课后报告只在同源下能跑** | 页面已接真实导出接口（`USE_MOCK` 那套 mock 已随前端重构移除）。生产由 FastAPI 同源托管，正常；但**后端没有 CORS 中间件**，前端跑 `localhost:3000`、后端在 `127.0.0.1:8000` 时请求会被浏览器拦掉。联调前需给 FastAPI 加 `CORSMiddleware`，或让前端走同源代理 | 中 |
| **报告可能缺少「未接触」的知识点** | 后端只在 `kp_stars` 有条目时才输出知识点，学生完全没碰过的不进数组，于是整个 `knowledge_points` 可能是空的，页面画不出「未检测」那些行。建议后端按课时知识点目录补全，未接触的返回 `stars: 0` | 中 |
| **后端 `STAR_STATUS` 只定义了 1–4 星** | 缺 0 和 5 两个键，所以一个 5 星知识点会被后端报成 `"status": "未检测"`。前端已按权威规则表本地兜底（不重算星级，只补标签），后端仍应补上这两个键 | 低 |
| **上传课时的判星链路是空的** | `EVIDENCE_GROUPS`（`agent.py`）是写死的旧课时关键词表。老师上传的新知识点没有对应组 → `match_evidence()` 返回 `(0, 0)` → 复述/探究阶段**不会靠关键词升星**，`judge_advance` 的「证据充分」分支也不会触发，只能按时间预算切幕。知识点能被讲、能被问（题库已按课时隔离，不会再借旧课的题），但星级到不了 3 星以上。解法是让上传时带 per-KP 关键词 | 中 |
| **课时定义无鉴权** | `POST /api/teacher/lesson` 会写盘且不需要凭证，而 `apps/start.py` 默认绑 `0.0.0.0`。局域网内任何人都能覆盖课时、进而向课堂注入任意提示词内容。生产部署前需要加 token 或反向代理 | 中（仅部署相关） |

已解决：~~无定时器~~（学生不发消息就无法切幕）—— 心跳时钟见上文「课堂里跑起来」。
