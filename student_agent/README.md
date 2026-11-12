# 平台会话鉴权说明

当前正式课堂请求：浏览器 Cookie → 平台 `/api/session/*` BFF → 学生服务内部身份校验。退出或登录到期不清除学习数据库。登录会话沿用 12 小时绝对期限；回答继续沿用 commandId 幂等和状态版本。

新增配置、切换顺序、测试证据与限制见 [实施记录](.personal-dev/docs/student-platform-session-auth/implementation.md)。正式前端及网关需与平台和学生服务一起更新，不能单独发布某一端。

# 学生端

结构化知识点的后续教学使用见 [教学使用方案](docs/knowledge-teaching/plan.md)，涵盖 State、一次 Agent 运行内的评估工具、程序固定选点、轮数限制及结束条件。上游知识点协议与提取已基本完成，相关设计和实施记录另见 [知识点提取文档](docs/knowledge-extraction/README.md)，两项工作分开维护。 新建三类型知识点会话现已接入首轮 5 轮、补强 8 轮和一次 Agent 工具教学流程，旧会话保持原方式；验证与限制见[实施记录](docs/knowledge-teaching/implementation.md)，未部署。

模块职责、接口、状态归属及动态教学渐进改造设计见 [从需求到模块架构设计](docs/student-module-architecture-design.md)。P1 收拢入口，P2 补齐可靠命令和事务，P3 增加任务/消息标识、学习证据、帮助记录与课时内容版本，默认继续既有教学流程。P4 提供显式白名单的新会话动态教学试点能力，未默认启用。变更与回归见 [P1](docs/student-p1-implementation.md)、[P2](docs/student-p2-implementation.md)、[P3](docs/student-p3-implementation.md)、[P4](docs/student-p4-implementation.md)、[P5 实施记录](docs/student-p5-implementation.md)。

现行目录按职责归位，详见 [目录与依赖说明](docs/student-directory-layout.md)。原 `agent/` 的业务源码已迁入 `backend/`，不再作为并列业务层：

```text
student_agent/
├─ backend/
│  ├─ main.py          HTTP 和应用启动入口
│  ├─ contracts.py     共享异常、稳定标识和流程名称
│  ├─ session/         学习会话编排、命令执行与恢复
│  ├─ teaching/        教学执行、LangGraph 和纯状态规则
│  ├─ evidence/        学习证据、帮助关联和反馈
│  ├─ content/         来源材料、提取和版本化内容模型
│  ├─ infrastructure/  数据库、内容存储、准备 worker、模型和平台 Adapter
│  └─ tests/           后端及真实数据库回归
├─ frontend/           Next.js 页面和学习交互 Module
├─ apps/               现有部署启动入口
├─ scripts/            部署脚本
└─ docs/               设计、实施说明和历史归档
```

平台负责登录、选课码加入课程和课程权限。当前同源课堂统一使用平台 Cookie 会话，经平台课堂 BFF 调用学生服务；浏览器不维护课堂启动令牌。课后补完与自由提问已接入，全班讨论尚未接入。

`apps/` 保留服务器现有启动命令使用的兼容入口，业务实现在 `backend/` 的职责包中。本地启动脚本仍是 `start-platform.ps1`；验证入口和部署命令不变。

`backend/main.py` 负责 HTTP 参数、路由、异常转换与静态页面；`backend/session/service.py` 统一编排会话恢复、换版、课堂/课后操作和保存；`backend/teaching/service.py` 封装既有教学图及消息阶段处理；`backend/infrastructure/platform_access.py` 负责平台上下文和学情同步；`backend/infrastructure/model.py` 共用模型调用与响应解析。教学阶段与规则沿用原有实现。

P2 新增 `backend/session/command_runtime.py` 与 `backend/infrastructure/commands.py`，正式页面的提交携带 commandId、stateVersion 和 contentGeneration。平台需先应用 `cmd11` 数据库迁移，再更新平台与学生代码；发布时暂停 P1 旧进程写入。恢复的权威依据是数据库快照，模型失败仍保留原回答供同命令重试。具体事务、兼容范围、隔离测试连接和维护排空方式见 P2 实施记录。

P3 新增 `backend/evidence/records.py` 与 `backend/content/lesson_content.py`；任务、证据和帮助与原消息同事务保存，学习中的会话固定 contentRef，整理器升级保留旧内容版本。正式浏览器快照仅作定位。发布 P3 前需暂停旧写入并应用 `rec12` 迁移；旧记录缺失的任务/帮助/独立性保持未知，不补造历史。

P4 新增 `backend/teaching/dynamic_teaching.py`，通过统一教学 Interface 执行受限动作、固定任务、独立尝试及证据反馈；新会话按可信课时白名单选择并固定 flowVersion/policy，旧会话继续 legacy。实际课时与真实模型抽样质量验收尚未执行，白名单默认为空。启用、限制和兼容回退见 P4 实施记录。

P5 新增前端 `learning-session.mjs`，统一课时恢复、请求/重试、准备与状态刷新；页面订阅 LearningView，动态会话按后端 allowedCommands 接入提示、例子、提问、暂停和继续。默认 legacy 教学和演示行为不变，未启用正式动态试点。

## 课堂流程

新建三类型会话使用[首轮逐点教学 → 补强未掌握点 → 总结](docs/knowledge-teaching/plan.md)。下文的 8/4 轮、后期确认及深入讨论规则仅适用于保留原版本的旧会话。

平台登录 → 使用选课码加入课程 → 选择课程 → 选择课时 → 教学视频 → 复述与讨论 → 本节课结束。教师发布视频时，平台登记该课时的视频版本和场景文字；学生服务后台提取知识点并保存到 `student.published_lesson_knowledge`。同一课时的学生读取这一份结果。视频嵌入逻辑沿用旧版 `platform-player-adapter.js`。视频页面可直接点击“进入复述与讨论”；播放结束也会给出提示。

平台首次只下发课时目录。点击“开始上课”时，后端携带所选课时 ID 再请求平台，取得该课时的视频地址、画面文字和旁白；其他课时的正文不会进入本次会话。旧课程在首次被选中时也会登记一次共享准备任务，供更新前已发布的视频使用。

教师发布后，学生服务从数据库领取准备任务并调用 `backend/content/knowledge.py`；失败自动重试，课堂页也可手动重试。学生开始上课时只读取当前视频版本的共享结果，不为每个学生调用一次模型。未准备好时可以观看视频，准备完成后进入复述与讨论；服务重启后继续处理未完成任务。演示模式仍在本地准备知识点。

部署时先执行平台迁移 `pub10_published_lesson_knowledge.py`，再更新教师端和学生端服务。三个 GitHub 自动部署工作流独立运行，发布这项跨服务改动时需要确保数据库迁移先完成。本机若已在下一版本分支执行过更高的 Alembic 修订号，可仅按本迁移创建任务表，保留现有迁移版本及数据。

后台整理从视频画面文字和旁白提取可复述的概念、原理和方法，剔除纯导入、课堂安排、过渡和未解答的问题。模型返回视频中的概念名称和原文依据；后端校验名称和解释确实出现在视频材料中，知识点描述直接保存所引用的视频原文。模型调用或格式校验失败时自动重试；没有实质知识点时提示教师检查视频内容。视频更新会产生独立的新版本知识点，不复用旧视频的提取结果。

对话共用一个页面，开场列出完整清单，再从第一个知识点开始逐项引导。首轮每个知识点最多 8 轮学生发言，不会时先提示；掌握则提前进入下一点，达到上限则留到加强复述。首轮全部走完后，加强复述处理未掌握的点，以及第 6～8 轮才掌握、仍需再确认一次的点，每点最多 4 轮。后者要在加强阶段独立解释一次概念，才能进入深入讨论。首轮超过 5 轮仍未掌握的概念会标记为重点强化，第二阶段会换简单表述或类比重新讲解，再请学生复述。加强后仍未掌握的点记录待巩固，不再进入深入讨论或出题范围。没有任何掌握点时不再出题，提示结束查看反馈。

`backend/teaching/progression.py` 控制顺序和计数。首轮上限由 `STUDENT_AGENT_RECALL_ROUNDS` 配置（默认 8），加强阶段上限由 `STUDENT_AGENT_REINFORCE_ROUNDS` 配置（默认 4）；两个值范围均为 1–20。开始课堂时保存上限，刷新不会清零。每次学生针对当前点发送消息计一轮，包括求助和表示不会；模型请求失败不计轮数。旧会话保留已知掌握结果，首次使用新流程时初始化分阶段计数。

结束本课后，`backend/evidence/feedback.py` 依据本次实际评估生成逐知识点反馈，区分掌握较好、加强后掌握、仍需巩固、评估未完成和尚未评估。初始与加强复述的概念掌握结果和深入讨论的应用题结果分别记录；讨论题答错不会抹掉先前的概念掌握，反馈会同时显示概念掌握依据和讨论题待巩固的依据。完成页可回看视频，也可进入课后 AI 对话。课后按待办队列继续概念复述、加强确认和未完成的讨论题，所有任务完成后才进入自由提问；学生独立讲清后标记“课后补完”，全部补完后在同一对话框自由提问。当前反馈作为 `lesson_feedback` 事件写入 `student.learning_events`（`event_id=final`），课堂结束时的原始反馈另存为 `classroom_feedback`。反馈与会话快照仍写入数据库；同一用户重新登录、清空浏览器存储或换设备后，选择原课时会经平台鉴权恢复数据库中的最新会话，浏览器快照仅作为定位线索。`GET /api/session/{sid}/feedback` 返回更新后的个人反馈。已有跨课次最高掌握度不用于替代本次课的实际结果。

新版本的开场文案、评估提示词、复述/补强/讨论提示词及各类对话策略统一维护在 `backend/teaching/prompts.py`；LangGraph 的状态跳转在 `backend/teaching/graph.py`。已保存的历史消息保留原文，新进入复述与讨论的课堂使用新的开场。

深入讨论对每个已掌握知识点各提出一个问题，只有当前题答对才进入下一个点；回答不完整、答错、表示不会或求助时，导师围绕原题提示，仍保留当前讨论题。最后一题答对后先给出简短反馈，再进入课堂总结。学生可主动提前结束，状态快照和个人反馈会记录提前结束及未完成的讨论题。加强复述后仍未掌握的点不会进入讨论。每轮学生消息由 LangGraph 调用模型评估与生成回复，阶段跳转由代码规则执行。正式课程会话、消息、知识点掌握度和 Agent 状态快照分别写入平台数据库的 `student.student_sessions`、`student.student_messages`、`student.knowledge_mastery` 和 `student.learning_events`。课时历史恢复始终通过平台可信身份查询数据库，不受 `STUDENT_FRESH_SESSION_MODE` 开关限制；该开关保留浏览器快照和旧式按会话编号读取的兼容行为。

## 退出重登与跨设备恢复

从平台重新登录并进入课程后，选择原课时即可恢复课堂消息、课后对话、个人反馈和学习进度，不要求当前浏览器保留原会话编号或快照。进行中的课堂直接显示历史消息；已结束课堂可展开“查看历史会话”，查看课堂与课后消息。前端调用 `POST /api/session/resume`，只提交课程 `course_id` 和所选 `lesson_id`；平台使用 HttpOnly Cookie 校验身份及课时访问权限，再按用户、课程、课时、发布版本和课堂绑定查找数据库的最新 `agent_state`。首次开始课时的 `begin` 接口使用相同的恢复逻辑。

数据库状态是正式课堂历史的依据。浏览器快照和进程内存过旧时，不得覆盖较新的数据库记录；正式课堂禁用 `browser-restore`，通过平台 Cookie 和课时定位重新读取数据库。独立演示模式仍可使用签名浏览器快照。

查无历史才进入首次学习流程；鉴权失败、历史不匹配或数据库暂不可用会显示错误，保留浏览器记录供重试。历史恢复只读取既有记录，不创建账号、不改动其他学生的数据。课程重新发布或课堂绑定变化后，不直接把旧版本学习状态应用到新版本；原有数据库记录仍保留。

离线回归可运行 `python -m pytest -q student_agent/backend/tests` 和前端目录下的 `npm run test:unit`。这些测试替换平台、数据库和模型边界，不启动服务、不连接运行中的数据库；前端构建使用 `npm run build`。

本节课结束页提供“重置本课学习进度”。确认后，后端按当前平台身份只删除这名学生这一课时的会话、消息、知识点掌握度与反馈，并同步教师端进度；浏览器删除本课快照，旧快照也不能恢复已删除的数据。其他课时保持原样，页面返回未学习的课时列表。

## 启动

教师重新发布同一课时的视频后，学生点击进入或恢复该课时时检查一次课堂 ID、发布时间及场景内容；更新时清除该会话的旧消息、评估、反馈和播放记录，并从新版视频重新开始。学习过程中不定时检查，提交回答和结束课堂也不额外检查。清理只针对当前学生的当前会话，其他课时不受影响。平台暂时不可用时保留原记录；旧版知识点整理任务不会覆盖新版课堂。

在 `frontend/` 中运行 `npm install` 和 `npm run build`，然后在 `backend/` 中安装 `requirements.txt`。本地平台已配置时，从项目根目录运行：

```powershell
.\student_agent\start-platform.ps1
```

脚本从本机 `platform/.env` 读取服务密钥和数据库地址，并设置 `PLATFORM_AUTH_URL`，监听 `127.0.0.1:8001`。Agent 优先使用 `STUDENT_AGENT_API_KEY`、`STUDENT_AGENT_BASE_URL`、`STUDENT_AGENT_MODEL`；本地未设置时读取本目录 `.env.local` 中的 `AGENT_LLM_*` 配置，仍可用平台的 `LLM_API_KEY` 兜底。数据库可用 `STUDENT_DATABASE_URL` 覆盖。平台启动脚本将 `/app` 转发到学生服务，将 `/api/session` 转发到平台后端统一鉴权。请从 `http://localhost:8088/login` 登录，在平台学生首页加入和选择课程，再点击“进入学习”。平台返回 `/app?course_id=...` 定位地址，不签发日常课堂启动令牌。平台和学生服务必须配置同一份独立 `PLATFORM_TO_STUDENT_KEY`；学生访问平台仍使用原 `STUDENT_SERVICE_KEY`。

若只想独立预览界面，设置 `STUDENT_DEMO_MODE=true`、`STUDENT_NEW_DEMO_PLAYER_URL` 和演示快照用的本地 `STUDENT_SERVICE_KEY`，清除 `PLATFORM_AUTH_URL` 与 `PLATFORM_TO_STUDENT_KEY`，只通过回环地址启动后端。演示模式不连接平台，也不包含平台登录与选课。

构建时前端会输出到 `frontend/out`，由 FastAPI 同源挂载到 `/app`。演示模式无平台身份，仅使用进程内会话，不写入正式学习数据库。

服务器现有 `agentic-student` 服务可继续通过 `apps/server.py` 或 `apps/start.py` 入口运行新后端（生产端口 8000）；本机启动脚本使用 8001。这两个入口只负责加载配置和启动，不包含旧学生端的教学逻辑。GitHub 的学生端部署工作流会安装 `backend/requirements.txt`、构建 `frontend/out` 并检查新服务健康状态。

## 回看验证

恢复课时时，课时列表使用目录摘要，当前课时使用恢复记录里的完整播放信息。如果回看地址缺失或播放器报错，可通过 `POST /api/session/{sid}/playback` 重新获取当前课时的播放信息；该接口校验学生、课程、发布版本和课堂绑定，不重启学习，也不修改反馈或对话。

后端验证：`python -m pytest -q student_agent/backend/tests`。浏览器回归验证在 `frontend/` 中运行 `npm ci`、`npx playwright install chromium --only-shell` 和 `npm run test:e2e`。浏览器用例使用模拟接口，覆盖直接回看、返回列表后恢复、从平台重新进入、缺失地址、失败重试及反馈与课后对话保留，不连接正式数据库。
