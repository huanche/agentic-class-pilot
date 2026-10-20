# 07: 本地测试用「当作已播完」开关

**What to build:** 学生端教学视频页提供一个**仅本地环境可见**的按钮「视频打不开？点这里当作已播完」：点击后走与播放器完全相同的 media/done 完成事件（触发进课后辅导）。开关由学生端环境变量 `AGENT_ALLOW_VIDEO_SKIP` 控制，默认**关**；`dev-8000-platform.ps1` 里默认置 true。生产不设该变量，按钮不存在——不违反「课堂阶段内无退出按钮」原则：它不是退出，是替不可用的教师端播放器补上同一个完成事件，且只在放视频这一步出现。

**Blocked by:** None (can start immediately)

**Status:** resolved

- [ ] `/state` 下发 `video_skip_allowed`（env 门控，默认 false）
- [ ] 视频面板（非回放）在开关开启时显示按钮；点击调用既有 notifyVideoEnd 路径；回放页不显示（Q17：回放不触发辅导）
- [ ] dev-8000-platform.ps1 默认开启；生产/CI 不设
- [ ] 缝 A：默认关、env 开两态断言
- [ ] 真机验证：8088 起环境后从注册到进辅导全程不碰教师端播放器

## Comments

### 2026-10-20 Claude（工单 07 实施）

**做了什么**（用户选定方向 2：本地测试专用，教师端播放器不方便常开时全链路仍可走通）

- `/state` 下发 `video_skip_allowed`（env `AGENT_ALLOW_VIDEO_SKIP`，取 1/true/yes/on，默认关）。
- 视频面板（stage-class.js `ensureDevSkipButton`）：开关开启且**非回放**时显示「视频打不开？点这里当作已播完（本地测试）」；点击走与播放器完全相同的 `notifyVideoEnd("skip")` → media/done 完成事件 → 进课后辅导。回放页不显示（Q17 回放不触发）。生产不设该变量，按钮不渲染——不违反「课堂阶段内无退出按钮」原则（它不是退出，是替播放器补同一个完成事件）。
- `dev-8000-platform.ps1` 默认置 `AGENT_ALLOW_VIDEO_SKIP=true`（本地常开）；生产 compose 不设。

**测试**

- 缝 A：`test_video_skip_flag_default_off_env_on`（默认 false / env true）。连同全套 65 过。
- 真机验证（对运行中的 :8000，教师端 3200 全程未参与）：注册→加入→开课→放视频→按钮可见→点击→#stage-chat 出现、徽标「课后辅导」、开场带编号知识点。探针显示点击后 ~25–45 秒切页——本机学生端带真实模型配置，开场润色本来就要 20–35 秒（stage-class.js 既有注释写明的行为，非本工单引入）。

**给使用者的说明**：本地想关掉这个按钮，把 `dev-8000-platform.ps1` 里 `AGENT_ALLOW_VIDEO_SKIP='true'` 删掉或改 false 重启即可。
