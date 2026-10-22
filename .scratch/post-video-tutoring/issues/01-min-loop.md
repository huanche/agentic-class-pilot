# 01: 最小闭环：视频完自动进入辅导阶段

**What to build:** 全局开关开启（默认开启，env 可关）时，视频最终完成事件后课堂直接进入新阶段「课后辅导」（host_phase 新值）：前端短暂过渡态（替换现有 20–30 秒"老师准备中"空窗）后，AI 自动发出开场消息——列出本节课知识点及固定数字编号，询问不理解之处、希望的复习顺序、自评星级、复习总时间（所有字段可省略）。复述、探究、讨论三阶段被开关下线（代码保留不删，开关关闭即回到原编排）。课后页"再看一遍"回放播完不触发辅导、不动已有会话。

**Blocked by:** None (can start immediately)

**Status:** resolved

- [ ] 开关开启：视频完成 → 进入辅导阶段（而非复述），AI 开场消息（知识点+编号+征询意愿）自动到达，学生无需点击任何按钮
- [ ] 开关关闭：回到原有编排（复述→探究→讨论），行为与现状一致
- [ ] 前端辅导阶段视图复用现有聊天 UI 与轮询机制；过渡态替换空窗文案
- [ ] 回放（#/replay）播完不进入、不重置辅导会话
- [ ] 开场消息内容由确定性骨架生成结构（知识点编号列表来自 learning-context），LLM 仅润色；LLM 用确定性桩在缝 A 测试上述全部行为
- [ ] demo 态与平台态均可运行

## Comments

### 2026-10-20 lzm（工单 01 实施）

**做了什么**

- 全局开关 `AGENT_POST_VIDEO_TUTORING`（默认开启，设 0/false/no/off 关闭）：开启时 `load_plan` 把序列里的复述/探究/讨论替换为一个 `tutoring` 阶段，关闭时序列原样、旧编排逐字回来（三阶段代码未删）。
- 视频最终完成（`media/done` final）→ 直接进 `host_phase=tutoring`；开场消息确定性骨架生成（知识点固定编号列表来自课时/知识库/平台 learning-context，`_lesson_kp_catalog` 统一取目录），LLM 只润色——模型不在时骨架原样说给学生（与 stage_opening 的 NO_LLM_NOTICE 降级不同，编号列表是硬性交付）。
- `judge_advance` 给辅导阶段加了"无时间出口"守卫：心跳/预算永远不会把学生踢出会话；老师按钮（下一环节/结束本节课）仍有效。
- 前端：`tutoring` 映射到现有 chat 界面与轮询（phases.js）；过渡态按后端 `next_stage` 区分文案——下一幕是辅导时说"正在进入课后辅导"，否则保持原有"等老师准备"文案（stage-class.js）；`startVideo` 改走统一舞台切换，修掉了"局部视频页导致阶段切换被短路"的问题。
- 回放不触发：前端 `#/replay` 本就不调 media/done（组件测试 replay.mjs 覆盖），后端下课会话拒收 media/done（409，缝 A 测试覆盖）。

**测试结果**

- 缝 A 新增 `apps/test_post_video_tutoring.py`（8 用例，含平台态 fixture 驱动）：`python -m unittest apps.test_api_integration apps.test_post_video_tutoring`（AGENT_LLM_API_KEY=""）→ 39 全过。
- 旧复述流程回归钉在开关关闭路径：`test_api_integration.py` 三个测试类显式设 `AGENT_POST_VIDEO_TUTORING=0`。
- e2e：`frontend/tests/e2e/tutoring-flow.spec.js` 2 用例过（真后端 + 确定性桩替播放器调 media/done）；playwright 拆双配置——默认跑辅导流程，`playwright.legacy.config.mjs`（开关关）跑旧 classroom-flow。
- 组件测试：新增 `tests/component/tutoring-transition.mjs`（过渡文案双态）过；`replay.mjs` 修掉对已删除的 `#btn-skip-video` 的等待后重新变绿。

**既有问题（非本工单引入，已实证基线同样红）**

- `classroom-flow.spec.js` 4 用例在基线上就全红：学生端早已挂到 `/app` 而 spec 仍 `goto("/")`（落在教师调试页），且引用的 `#btn-skip-video` 已在 03c3866 移除。已用 git stash 在原始代码上复跑证实。
- `npm run lint` 基线上就 1 error 1 warning（eslint "latest" 漂移触发 StudentApp.js 的 set-state-in-effect 规则）。

**演示路径（本地 8088 全家桶）**

1. 起 8088 环境，学生端登录 → 课程码加入 → 进「处理机调度」课时 → 开始上课。
2. 点「开始播放教学视频」，等视频自然播完（或教师端播完）。
3. 视频页出现"正在进入课后辅导…"过渡文案，随后自动切到聊天界面、徽标变「课后辅导」，AI 开场消息带知识点编号 1–6 与征询项自动到达，全程无需点击。
4. 直接打字（如"先复习 2，15 分钟"）即可对话；F5 刷新后会话与开场消息原样恢复。
5. 关闭验证：环境变量 `AGENT_POST_VIDEO_TUTORING=0` 重启后，同一流程回到复述→探究→讨论。

**给后续票的注意事项**

- 票 02（消息分类）：teach 的 tutoring 分支已留好挂点——现在只做"确认意愿 + 邀请讲第一个知识点"，分类判定应替换该分支内的 directive 构造，骨架函数 `_lesson_kp_catalog` 可直接复用做知识点锚点。
- 票 03（时间预算）：`judge_advance` 的辅导守卫注释里标了"到点只改教学安排"的接入位；计划结束时间戳建议放 state 新键而非复用 stage_started_at。
- 星级/自评/反馈表（04/05）未动 student schema；`_lesson_kp_catalog` 的 (kp_id, title) 序对可直接作掌握条的目录源。
- e2e 旧套件（classroom-flow）与 lint 的既有红需要单独的清理票，别混进功能票。
