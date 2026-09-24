# 主动引导智能体

一个由**课程计划驱动、AI 自动推进**的课堂智能体。

> 本仓库是 `HELLO-APL/Dify-Classroom-Interactive-Agent` 的重构版。
> 旧仓库 `D:\project\Dify 课堂互动智能体` 保留不动，仅作参照。
>
> **主要变化**：移除学生标注 · 移除 n8n 与前端 · 改为四阶段（可配置）编排模型 · 新增 LangGraph 编排结构 · 目录改为无空格英文命名。

---

## 这是什么

学生端不是一个"学生问、AI 答"的聊天机器人，而是**一个按老师排好的课程计划自动推进的课堂**：

```
老师配置 lesson-plan.json  ──→  AI 每轮读计划 + 判证据 + 判耗时  ──→  自动切幕
（上几个阶段、每阶段多久）        （编排器 host_phase 状态机）          （把课上完）
```

**核心设计：** 提示词负责"怎么教"，数据负责"教什么、按什么顺序教、多久教完"。改课程结构不用改提示词。

> **本仓库只做智能体逻辑与规则，不含前端、不含 n8n。**
> 所有产物是 Markdown 规则 + JSON 配置 + 一份编排规范。

---

## 环境配置

### 1. 版本要求

| 组件 | 要求 | 用在哪 | 不满足的后果 |
| --- | --- | --- | --- |
| **Python** | **≥ 3.10**（开发机 3.11.4） | 后端、编排器、全部脚本 | 3.9 及以下直接起不来：请求模型用了 `str \| None`（PEP 604 写法，3.10 才支持） |
| **Node.js** | **≥ 20.9.0**（开发机 22.16.0，自带 npm） | **只**用于构建学生端页面 | 不装也能上课，只是 `/app` 学生端页面打不开 |
| 大模型 Key | 可选 | 润色老师的讲解措辞 | 不配也能上完整节课，讲解词走确定性降级脚本 |

> **只有要重新构建 `frontend/` 时才需要 Node.js。** 后端 + 编排器 + 命令行上课是纯 Python。

### 2. Python 依赖

```bash
python -m pip install fastapi uvicorn langgraph
```

| 包 | 谁在用 | 干什么 |
| --- | --- | --- |
| `fastapi` | `apps/server.py` | HTTP 接口 + 托管学生端 / 老师页 |
| `uvicorn` | `apps/start.py` · `apps/server.py` | ASGI 服务器 |
| `langgraph` | `orchestrator/agent.py` · `run_demo.py` | 编排状态图（11 节点） |

`apps/cli.py`、`apps/smoke_test.py`、`orchestrator/clock_reference.py` 本身只用标准库，但它们要连的服务端依赖上面三个。

| 缺哪个 | 启动时的表现 |
| --- | --- |
| `fastapi` / `uvicorn` | `apps/start.py` 直接报出缺哪个并给出安装命令；`apps/server.py` 抛 `SystemExit("缺依赖：pip install fastapi uvicorn")` |
| `langgraph` | 抛 `ModuleNotFoundError: No module named 'langgraph'`（`server.py` 在 import 阶段就拉 `agent.py`）—— 装上即可，不用改代码 |

### 3. 环境变量

**全部可选。** 不配任何变量也能跑完整节课。下面是全部变量，以及两种给法（优先级从高到低）：

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `AGENT_LLM_BASE_URL` | 空 | 任意 OpenAI 兼容端点，如 `https://api.deepseek.com/v1` |
| `AGENT_LLM_API_KEY` | 空 | 端点 Key |
| `AGENT_LLM_MODEL` | 空 | 模型名，如 `deepseek-chat` |
| `AGENT_TICK_SECONDS` | `10` | 心跳时钟间隔（秒）。调小 → 切幕判断更密 |
| `AGENT_PORT` | `8000` | 直接 `python apps/server.py` 时的端口；走 `apps/start.py --port` 时以命令行为准 |

**`AGENT_LLM_*` 三个必须同时给**：缺任意一个，`teach` 节点就退回确定性脚本 —— 编排结果一字不差，只是老师的话变成模板文案（见下文「接真实大模型」）。

**首选：建 `.env.local`**（已在 `.gitignore`，不会提交）

```bash
cp .env.local.example .env.local      # Windows CMD: copy .env.local.example .env.local
# 然后填入 Key
python orchestrator/llm_probe.py      # 先单独验证端点通不通
```

文件从**仓库根目录**读取，支持 `.env.local` 与 `.env` 两个名字；**已存在的同名环境变量不会被文件覆盖**，所以临时用命令行覆盖很方便。

**次选：直接用环境变量**

```bash
export AGENT_LLM_BASE_URL=https://api.deepseek.com/v1   # Windows PowerShell: $env:AGENT_LLM_BASE_URL="..."
export AGENT_LLM_API_KEY=sk-xxx
export AGENT_LLM_MODEL=deepseek-chat
```

### 4. 首次运行顺序

```bash
python -m pip install fastapi uvicorn langgraph   # ① 装依赖
# ② 可选：根目录双击 构建前端.cmd  —— 只有要 /app 学生端页面才做
# ③ 根目录双击 启动课堂.bat，或：
python apps/start.py
```

`启动课堂.bat` 先找 `.workbuddy\binaries\python\envs\default\Scripts\python.exe`（开发机的隔离环境），**找不到就退回系统 `python`** —— 换机器不用改脚本，保证 `python` 在 PATH 里即可。

---

## 目录结构

```
主动引导智能体/
├── rules/                       # 规则层（AI 每轮只读，老师维护）
│   ├── KNOWLEDGE-BASE.md        # 知识点目录（含 4 个探究字段）
│   ├── interaction/             # 课堂节奏规则、判星规则、各文件格式模板
│   │   ├── SKILL.md             #   课堂互动 Skill（阶段行为）
│   │   ├── MASTERY-STAR-RULES.md   # 0-5 星唯一权威规则
│   │   └── *-FORMAT.md          #   七个运行时文件的字段模板
│   └── dialogue/SKILL.md        # 对话 Skill（学生轮次路由）
│
├── lesson-data/                 # 课程数据层（老师配置）
│   ├── lesson-plan.json         #   ★ 编排入口：阶段开关 + 时长预算 + 推进策略 + 时钟策略
│   └── segments/seg-XXX.json    #   课程片段（order 定顺序，绑定 KP）
│
├── stages/                      # 阶段内容层（可空壳，留空不影响运行）
│   ├── recap_discussion/        #   复述：questions.md / rubric.md / prompt.md
│   ├── deep_inquiry/            #   深挖：questions.md / rubric.md / prompt.md
│   └── class_discussion/        #   讨论：questions.md / rubric.md / prompt.md
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
├── frontend/                    # ★ 学生端页面（Next.js 源码，静态导出的）
│   ├── src/legacy/              #   路由、课堂面板、学情报告、接口层 api.js
│   └── next.config.mjs          #   output:'export' + basePath:'/app'
│
├── apps/                        # 会话层：把编排器接进真实对话
│   ├── server.py                #   ★ FastAPI：开课 / 发言 / 心跳时钟 / 学情导出 / 托管前端
│   ├── smoke_test.py            #   ★ 课前彩排脚本（不发言跑完一节课）
│   ├── static/index.html        #     老师页（对话 + 三个按钮 + 进度条）
│   └── static/app/              #     前端构建产物（生成物，不入库）
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

先按 **「环境配置」** 装好 Python 依赖（`python -m pip install fastapi uvicorn langgraph`），然后：

```bash
python orchestrator/run_demo.py        # 模拟一节课（讲解 → 复述 → 探究 → 下课）
```

### 课堂里跑起来（一键）

**双击项目根目录的 `启动课堂.bat`** —— 起服务、自动开浏览器、打印局域网地址，就这样。

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
| **学生端页面** | 构建后打开 `http://127.0.0.1:8000/app` | 学生。完整的四阶段界面 + 课后学习报告 |
| 老师页 | 浏览器打开 `http://127.0.0.1:8000/` | 老师。自带「开始上课 / 视频播完 / 下一环节」三个按钮 |
| **命令行窗口** | `python apps/cli.py` | 不等前端时直接上课：`/begin` `/video` `/next` 是三个按钮，直接打字是学生发言 |
| HTTP API | 见 **`apps/API.md`** | 前端同学对接用：全部接口、字段、时序图、curl 示例 |

### 学生端页面（`/app`）

学生端是一个 Next.js 应用，源码在 `frontend/`，**静态导出**后由 FastAPI 挂在 `/app`
（同源，所以不需要 CORS）。改过前端代码要重新构建（需要 **Node.js ≥ 20.9**，见「环境配置」）：

```bash
# 根目录双击 构建前端.cmd，或：
cd frontend && npm ci && npm run build
# 再把 out/ 同步到 apps/static/app/
```

> `apps/static/app/` 是构建产物、不入库。**没构建过也不影响上课**（老师页与命令行照常），
> 只是 `/app` 会返回 404 并提示「前端还没构建」。

它跟后端的分工是：**前端不做教学判断**。讲哪一段、问哪一题、什么时候切幕、打几星
全由编排器决定，前端每 2 秒轮询 `/state` 和 `/messages` 跟随，按钮照 `available_actions` 渲染。
课后学习报告读的是 `/api/session/{sid}/export?fmt=json`。

细节见 `frontend/README.md`；接口契约以 `apps/API.md` 为准。

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
变量名与配置方式见上文 **「环境配置」第 3 节**，这里是要跑的命令：

```bash
cp .env.local.example .env.local    # Windows CMD: copy .env.local.example .env.local
# 填入 Key（该文件已进 .gitignore）
python orchestrator/llm_probe.py    # 先单独验证端点通不通
python orchestrator/run_demo.py     # 再跑整节课
```

> **模型只负责措辞，不负责编排。** `teach` 分两层：确定性骨架决定"讲哪段、问哪题"，
> 模型把指令润色成自然语言。所以模型挂了课照常上完，切幕与星级一字不差。
> 已验证：有/无 LLM 两种方式跑同一串时间戳，剔除老师说的话后 **51 行编排结果逐行相同**。
> 详见 `ORCHESTRATOR.md` 第 3.1 节。

演示输出会标出每轮回复的来源：`老师[AI  ]>` 是模型生成，`老师[脚本]>` 是降级文案。

---

## 五个阶段

| 阶段 | `host_phase` | 时间 | 干什么 | 星级影响 |
| --- | --- | --- | --- | --- |
| 开场 | `intro` | — | 交代目标与互动方式 | — |
| 引导学习 | `guided_learning` | 0-50% | 讲解 + 主动提问 | 1 星（已接触） |
| 复述与讨论 | `recap_discussion` | 50-70% | 学生复述，AI 补缺口 | 2-3 星 |
| 深层探究 | `deep_inquiry` | 70-85% | 追问为什么/如何/用在哪/跨学科 | 4 星 |
| 全班讨论 | `class_discussion` | 85-100% | 老师主导，AI 退居协助 | 只记快照 |
| 收尾 | `ending` | — | 总结 + 遗留问题 | — |

**阶段可自由启停**：`lesson-plan.json` 里 `enabled: false` 即可跳过。

---

## 老师配一门课：三步

### 1. 定阶段与时长

编辑 `lesson-data/lesson-plan.json`：

```json
{
  "lesson_id": "ch3-process-scheduling",
  "total_minutes": 45,
  "stages": [
    { "id": "guided_learning",  "enabled": true,  "minutes": 22, "advance_when": "either" },
    { "id": "recap_discussion", "enabled": true,  "minutes": 9,  "advance_when": "either" },
    { "id": "deep_inquiry",     "enabled": true,  "minutes": 7,  "advance_when": "either" },
    { "id": "class_discussion", "enabled": false, "minutes": 7,  "advance_when": "budget" }
  ]
}
```

| 字段 | 含义 |
| --- | --- |
| `enabled` | `false` → **整段跳过**（比如这门课不要讨论） |
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
| 各阶段的问题与评判标准 | `stages/<阶段>/questions.md` · `rubric.md` | **暂不填（按需）** |

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
| `class_discussion` 无内容 | AI 提示"请老师主导"+ 计时，然后切幕 |

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
| **前端** | 本仓库不再包含 `apps/`、课堂页面、学生 workspace 页面 |
| `LESSON-INTERACTION.md` | 改名为 `LESSON-CONTENT.md`（旧名与实际内容不符） |

---

## 关键文档

| 文档 | 内容 |
| --- | --- |
| `orchestrator/ORCHESTRATOR.md` | **编排器结构**：LangGraph 状态 schema、节点、条件边、文件调度、校验规则 |
| `orchestrator/MIGRATION.md` | 新旧路径映射与变更记录 |
| `rules/interaction/MASTERY-STAR-RULES.md` | **0-5 星唯一权威规则** + 阶段快照机制 |
| `rules/interaction/DIALOGUE-LOG-FORMAT.md` | 会话状态字段（含编排器字段） |
| `rules/interaction/LESSON-CONTENT-FORMAT.md` | `LESSON-CONTENT` 与 `TMISSION` 的分工 |
| `stages/*/README.md` | 各阶段在干什么、没配置时怎么降级 |

---

## 已知缺口（待解决）

| 缺口 | 影响 | 优先级 |
| --- | --- | --- |
| **对话日志文件仍共享** | 掌握档案已按学生隔离（`runtime/students/<student_id>/`，2026-09-21 起），但 `runtime/DIALOGUE-LOG.md` 与 `data/dialogue.json` 仍是全课共享文件——多人同上时日志内容会混在一起，**不影响判定与星级**，只影响日志可读性 | 中 |
| **对话记忆窗口有限** | 长课程可能丢上下文 | 高 |
| **视频位置接口未打通** | `source.position` 是占位符 | 中 |
| **判星粒度未定** | 各阶段星级的精确判定标准待明确 | 中 |
| **`class_discussion` 内容为空** | 当前刻意留空，AI 不参与讨论 | 低（设计如此） |

已解决：~~无定时器~~（学生不发消息就无法切幕）—— 心跳时钟见上文「课堂里跑起来」。
