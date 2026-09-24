# STORY.md — 主动引导智能体 · 项目介绍

## ① 用户意图对齐

- **目标受众**：项目评审 / 技术分享场合。观众 = 老师（使用者）+ 开发者 / 评审（技术把关人），半专业受众。
- **核心目标**：听完能回答四个问题——学生上课经历什么？老师课前要配什么（配在哪、谁在读）？编排器代码怎么转起来的？仓库里每个文件是干什么的、何时被谁调用？最终相信"这套系统现在就能跑，且改课程不用改代码"。
- **PPT 长度**：18 页（Hero 配额 4 页：封面 / 六幕时间轴 / LangGraph 图 / 结束页）。
- **视觉调性**：科技深蓝、工程感、结构化、清晰克制。
- **内容边界**：必讲——四视角（学生流程 / 老师配置 / 编排器代码 / 文件板块地图）、每个文件的用途与调用时机。不讲——旧仓库细节、前端与 n8n（已移除）、部署运维。

## ② 页面布局骨架

**分章（目录 4 章 ↔ 4 个 section 扉页，一一对应）**：

| 目录章节 | section 扉页 | 页码区间 |
| --- | --- | --- |
| 01 学生端 · 一节课的完整旅程 | P03 | P03–P05 |
| 02 老师端 · 课前配置 | P06 | P06–P09 |
| 03 编排器 · 代码实现 | P10 | P10–P14 |
| 04 功能板块 · 文件地图 | P15 | P15–P17 |

**Hero 页**：P01（封面）、P04（六幕时间轴）、P11（LangGraph 图）、P18（结束页）= 4/18 ≈ 22%，两两间隔 ≥ 1 页 supporting ✓

**rhythm 曲线**：P01 peak → P02 valley → P03 transition → P04 peak → P05 valley → P06 transition → P07 valley → P08 valley → P09 peak（"空壳也能跑"结论页打破三连 valley）→ P10 transition → P11 peak → P12 valley → P13 valley → P14 valley → P15 transition → P16 valley → P17 valley → P18 peak

**非对称版式预算**：P01 骑线文字 / P02 左标题右内容 / P04 时间轴 / P07 非对称双栏 / P08 左标题右内容 / P11 全幅图 / P14 非对称双栏 / P16 左树右表 → 8/18 ≈ 44% ✓
**对称版式**：P05 图表+洞察（表格）、P09 上下分栏、P12 全宽表格、P13 上下分栏、P17 全宽表格 —— N卡片横排 0 页 ✓

## ③ 页面大纲

| # | title | type | role | rhythm | layout | visual | visual_role | density | anti_pattern | description |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 01 | 主动引导智能体 | cover | hero | peak | 全屏视觉+骑线文字 | L1: 左色带+右侧几何线框（SVG） | anchor | 约40字 / 留白40% | 禁止标题旁塞 200×70 小图 | 课程计划驱动、AI 自动推进的课堂智能体——提示词管"怎么教"，数据管"教什么、教多久" |
| 02 | 目录：四个视角看懂这套系统 | catalog | supporting | valley | 左标题+右内容 | L3: 页脚徽标 | — | 约140字 | 禁止四卡片等宽横排 | 学生端流程 / 老师端配置 / 编排器代码 / 功能板块文件地图，每章标注页码区间 |
| 03 | 01 学生端 | section | transition | transition | 章节大字 | L1: 大号"01"+一句导语（SVG 装饰线） | atmosphere | 约35字 / 留白45% | 禁止铺满段落 | 学生在课上不是"问答机器人对面的人"，而是被一堂有剧本的课带着走 |
| 04 | 一节课的六幕：时间表就是剧本 | content | hero | peak | 时间轴（SVG 全宽） | L1: 六幕时间轴 Diagram（占B区≥50%） | anchor | 约120字 / 图1 / 留白20% | 禁止把幕拆成等宽小卡横排 | 45 分钟课：开场→讲解22′→复述9′→探究7′→（讨论7′可关）→收尾。时长占比来自 lesson-plan.json 真实配置 |
| 05 | 逐幕体验与星级成长 | content | supporting | valley | 图表+洞察（表格） | Chart(Table) + 洞察框 | evidence | 约260字 | 禁止纯文字罗列六段 | 每幕学生做什么、AI 做什么、星级怎么变：讲解1星→复述2-3星→探究4星→考核5星；星级只升不降 |
| 06 | 02 老师端 | section | transition | transition | 章节大字 | L1: 大号"02" | atmosphere | 约35字 / 留白45% | 禁止四卡片预览 | 老师不用写提示词，只填配置和内容文件 |
| 07 | 第一步：lesson-plan.json 定阶段与时长 | content | supporting | valley | 非对称双栏（左代码右表） | L2: CodeBlock(JSON) | evidence | 约200字 | 禁止左右 50:50 等分 | stages[] 的 enabled/minutes/advance_when 三字段 + advance_policy 四参数，改 JSON 即改课 |
| 08 | 第二步：填课程内容（写在哪、谁在读） | content | supporting | valley | 左标题+右内容 | Chart(Table) 文件地图 | evidence | 约280字 | 禁止等宽四卡 | KNOWLEDGE-BASE / TMISSION / LESSON-CONTENT / segments / stages 五类文件：用途、何时被编排器读取 |
| 09 | 空壳也能跑：降级链与启动校验 | content | supporting | peak | 上下分栏 | 大结论 + 两组清单 | anchor | 约220字 | 禁止把校验清单排成流水账 | 三级兜底提问链 + 8 项启动校验——阶段内容留空照样开课，填了质量自然提升，不用改代码 |
| 10 | 03 编排器 | section | transition | transition | 章节大字 | L1: 大号"03" | atmosphere | 约35字 / 留白45% | — | 一个由 host_phase 驱动的课堂状态机：每轮读计划→判证据+判耗时→写回切幕 |
| 11 | LangGraph 图：11 个节点一条环 | content | hero | peak | 全幅图+骑线文字（SVG 流程图） | L1: 节点流程图（占B区≥55%） | anchor | 约110字 / 图1 | 禁止用 mermaid 远程渲染 | 自动推进的本质 = 图里有个环：学生每说一句话就走一圈、重新判一次切幕 |
| 12 | 节点职责 × 文件调用对照 | content | supporting | valley | 图表+洞察（全宽表格） | Chart(Table) | evidence | 约300字 | 禁止把 11 行拆成多页 | 每个节点读什么文件、写什么状态/文件：load_plan→lesson-plan.json，judge_mastery→rubric+星规则，write_state→runtime/** |
| 13 | teach 两层铁律：模型只管措辞 | content | supporting | valley | 上下分栏 | L1: 两层结构图（SVG） | evidence | 约240字 | 禁止只放文字不画两层 | 确定性骨架决定"讲什么/问什么"，LLM 只润色"怎么说"；有/无 LLM 跑同串时间戳，51 行编排结果逐行相同 |
| 14 | 真实时钟 tick 与切幕判定 | content | supporting | valley | 非对称双栏 | CodeBlock(python) + 判定顺序表 | evidence | 约240字 | 禁止把判定顺序写成段落 | now 由会话层注入、节点只做减法；judge_advance 短路判定 5 步：防秒切→学透才走→证据达标→预算耗尽→留幕 |
| 15 | 04 功能板块 | section | transition | transition | 章节大字 | L1: 大号"04" | atmosphere | 约35字 / 留白45% | — | 五个目录五种角色：规则 / 课程数据 / 阶段内容 / 运行时 / 编排器 |
| 16 | 五大板块：每个文件归谁管 | content | supporting | valley | 左树右表（非对称） | L1: 目录树（SVG/文本树） | anchor | 约300字 | 禁止只画树不给用途 | rules/ lesson-data/ stages/ runtime/ orchestrator/ 逐目录说清：放什么、谁写、谁读、何时读 |
| 17 | 上下文分层装配与数据落盘 | content | supporting | valley | 全宽表格+洞察 | Chart(Table) 六层装配表 | evidence | 约280字 | 禁止把六层写成列表段落 | 规则层/计划层/课堂层每轮装，阶段层按幕装，档案层仅判星装——45 分钟课上下文永远"刚好够用" |
| 18 | 现在就能跑 | ending | hero | peak | 居中金句+命令 | L1: CodeBlock(命令) + 金句 | anchor | 约90字 | 禁止堆已知缺口长表 | pip install langgraph → run_demo.py；接 LLM 三行环境变量。模型挂了课照常上完 |

## 数据必须落点（关键数字 → 判断）

- 45 分钟 / 22′+9′+7′ → 时间预算来自老师配置，编排器对真实时间负责，不对"聊了几轮"负责
- 11 个节点 → 职责单一、可单测；切幕判定只有一处（judge_advance）
- 51/51 行逐行相同 → teach 两层分离被验证：模型不架空编排
- 0-5 星、5 星只能考核给出 → 证据先于评价，星级不是聊天聊出来的
- 8 项启动校验 → "目前能不能上课"是确定性判断，不依赖模型
