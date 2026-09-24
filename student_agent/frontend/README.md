#  AI 学习空间 · 学生端

面向学生的 AI 课堂前端。把「每节课 4 阶段逐步加深」的教学模型做成学生看得见的界面。

基于 **Next.js App Router + React** 实现。课堂主体运行在 Client Component 中，后端仍保持为独立服务；前端只根据后端下发的 `hostPhase` 更新课堂阶段。

---

## 教学模型

一节课拆成 4 个阶段，每阶段占课堂时间的固定比例：

| 阶段 | 时间占比 | 学生做什么 | 界面上是什么 |
| --- | --- | --- | --- |
| **引导学习** | 0–50% | 听讲解、看视频、随时提问 | AI 对话 + 教学视频 |
| **总结复述** | 50–70% | 用自己的话把刚学的讲一遍 | 对话框中提交总结并查看 AI 反馈 |
| **深入思考** | 70–85% | 想底层逻辑、实际问题和跨学科关系 | 对话框中依次回答三个视角的问题 |
| **课堂讨论** | 85–100% | 老师引导，同学之间交流 | 老师 / 同学 / 我 的讨论区 |

页头右上方始终显示**当前处于哪一幕**（课程介绍 / 引导学习 / 总结复述 …）。页面和课堂阶段切换会立即完成，不播放切换动画。

**前端不决定演到哪一幕。** 每次后端响应回来后比对 `hostPhase`，变了才切界面 —— 切幕时机由后端的编排器 `judge_advance` 决定（真实时钟 + 证据 + 策略，见 `docs/architecture/ORCHESTRATOR.md`）。

---

## 功能

- **选课**：选课程 → 选课时。目录目前就是后端 `lesson-data/lesson-plan.json` 里配的那一节课（操作系统 · 第 3 周 处理机调度）
- **课时入口**：课堂与课后两张卡都在 —— 课堂随时能进（后端 `/start` 幂等，已结束的会话也能恢复），课后报告在没上过课时显示空态
- **课堂**：完整流程走真实后端 —— 课前 → 开始上课（起课铃）→ 讲解视频 → 总结复述 → 深入思考 → 结束态。演到哪一幕由后端的 `host_phase` 决定，前端轮询跟随，自己不做教学判断
- **对话区**：课堂聊天、总结复述、深入思考采用统一的固定尺寸，消息在框内滚动
- **课后 · 学习报告**：知识点掌握（0–5 星）、各阶段表现、课后建议。数据来自后端的学情导出，只呈现学生自己的部分，不展示教师侧的会话标识与原始证据摘录
- **深浅色主题**：浅色 / 深色 / 跟随系统，右上角切换，带首屏防闪
- **视频**：只保留外部播放器挂载接口；业务方播放器负责渲染与播放结束回调
- **响应式**：窄屏卡片改单列
- **动效**：保留消息、提示和悬停等局部反馈；页面与课堂阶段切换不播放动画
- **可访问性**：键盘可达、焦点管理、`aria-live` 会话区

---

## 怎么跑

这一份前端是**挂在后端里**的：`next build` 静态导出成静态文件，由 FastAPI 挂到 `/app`。
同源，所以不需要 CORS。

```bash
# 1. 构建（改过 src/ 之后要重跑）
cd frontend && npm ci && npm run build
#    产物 out/ 同步到 apps/static/app/ —— 根目录双击 构建前端.cmd 会一步做完

# 2. 起服务
python apps/start.py --no-browser
# 3. 打开
http://127.0.0.1:8000/app
```

后端自带的老师页仍在 `http://127.0.0.1:8000/`。

> **改样式/改文案时的循环**：构建只要几秒，所以直接 `npm run build` + 同步 + 刷新页面最快。
> `npm run dev` 也能起（会挂在 `http://localhost:3000/app`），但那个端口上没有后端，
> 接口会全部 404 —— 因为 `output: 'export'` 和转发规则（`rewrites`）不能共存，
> 所以开发服务器没法把 `/api` 代理到后端。要调接口就用单端口那套。

---

## 环境配置

### 环境要求

- Node.js **20.9 或更高版本**
- npm（随 Node.js 一起安装）
- Chrome 111+、Edge 111+、Firefox 111+ 或 Safari 16.4+

可以先确认本机环境：

```bash
node --version
npm --version
```

### 快速配置

拿到项目后，在项目根目录执行以下命令即可安装依赖并启动开发环境：

```powershell
# Windows PowerShell
npm ci
npm run dev
```

```bash
# macOS / Linux
npm ci
npm run dev
```

启动成功后打开 <http://localhost:3000>。项目默认使用本地 Mock 数据，因此无需配置后端即可体验全部现有流程。

Windows 用户也可以直接双击根目录的 `启动演示.cmd`，脚本会在首次启动时自动安装依赖并打开页面。

### 后端地址

项目默认使用本地 Mock 数据，不启动后端也能完整体验课堂流程。

需要连接独立后端时，在项目根目录复制环境变量模板：

```powershell
# Windows PowerShell
Copy-Item .env.example .env.local
```

```bash
# macOS / Linux
cp .env.example .env.local
```

然后修改 `.env.local`：

```dotenv
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

同时把 `src/legacy/api.js` 中的 Mock 开关改为：

```js
export var USE_MOCK = false;
```

说明：

- 不设置 `NEXT_PUBLIC_API_BASE_URL` 时，请求默认发送到当前前端域名下的 `/api`。
- 前后端不同端口或域名时，后端需要允许前端地址进行 CORS 请求。
- `.env.local` 必须放在项目根目录，不要放进 `src/`，也不要提交到 Git。
- `NEXT_PUBLIC_` 变量会进入浏览器端代码，不能在其中保存密码、Token 或其他机密信息。
- 修改 `.env.local` 后需要重新启动开发服务器；生产环境变量需要在执行 `npm run build` 前设置。

## 快速启动

### Windows 双击演示

双击项目根目录的 [启动演示.cmd](启动演示.cmd)。脚本会检查 Node.js、首次运行时自动执行 `npm ci`、选择 3000–3010 中的空闲端口，并在服务就绪后打开浏览器。保持启动窗口打开；演示结束后在窗口中按回车停止服务。默认使用 Mock 数据，无需启动后端。

如果本项目的开发服务已经在运行，再次双击会直接打开已有页面，不会重复启动。`node_modules/` 是运行依赖，`.next/dev/` 是加快后续开发启动的缓存；不要为了减少文件数而在每次启动前删除它们。

也可在 PowerShell 中运行 `./scripts/start-demo.ps1`。

### 命令行启动

在项目根目录依次执行：

```bash
# 1. 按 package-lock.json 安装确定版本的依赖
npm ci

# 2. 启动开发服务器
npm run dev
```

浏览器打开：

```text
http://localhost:3000
```

如果 `3000` 端口被占用，Next.js 会提示实际使用的地址，也可以手动指定端口：

```bash
npm run dev -- --port 3001
```

### 生产环境启动

```bash
# 先执行代码检查
npm run lint

# 创建生产构建
npm run build

# 启动生产服务器
npm start
```

生产服务器默认访问地址同样是 `http://localhost:3000`。

---

## 目录结构

```
.
├── src/
│   ├── app/
│   │   ├── layout.js       根布局、页面元数据与主题首屏防闪
│   │   ├── page.js         学生端入口页面（Server Component）
│   │   └── globals.css     全局设计令牌与组件样式
│   ├── components/
│   │   ├── StudentApp.js   课堂客户端边界与初始化入口
│   │   ├── courseMarkup.js 课程与周次选择界面
│   │   └── legacyMarkup.js 迁移期间保留的页面结构
│   └── legacy/             课程目录、课堂状态机、阶段与 API
├── public/                 Next.js 静态资源目录
├── next.config.mjs     Next.js 配置
├── package.json        依赖与开发/构建命令
├── docs/
│   ├── architecture/       架构、运行流程、编排器规范和 Mermaid 流程图
│   └── api/                后端接口契约
├── .env.example        后端地址配置示例
└── jsconfig.json       `@/` 指向 `src/`
```

**路由**（hash，刷新与前进后退都能用）

| hash | 页面 |
| --- | --- |
| `#` | 我的课程 |
| `#/course/:courseId` | 该课程已开放的周次 |
| `#/lesson/:courseId/:lessonId` | 该课时的课堂 / 课后入口 |
| `#/class/:courseId/:lessonId` | 课堂 |
| `#/review/:courseId/:lessonId` | 课后 |

演示目录以 2026-09-01 为学期起点计算当前周；此前周次假定已经上过，当前周可学，未来周次隐藏。真实接入时应由后端按学生选课、教师发布和实际授课进度返回 `status: completed | current | upcoming`，不能仅靠日历推断。每个课时使用独立的会话 ID。课堂里没有返回按钮，`Esc` 也禁用 —— 一旦开课就走完四个阶段。

---

## 技术说明

**Next.js 负责应用入口、根布局、页面元数据、全局样式和生产构建。** 当前迁移优先保证行为等价：原有课堂编排模块作为客户端兼容层挂载，后续可以按阶段逐步替换成独立 React 组件，而不需要再次改动接口契约。

**课堂主体是 Client Component。** 外部播放器挂载、主题、输入框、局部反馈动画、`localStorage` 与实时会话都依赖浏览器能力；后端接口仍然通过 `src/legacy/api.js` 访问，不在 Next.js 中重复实现业务后端。

**界面切换不依赖动画。** Hash 页面、课堂 Stage、总结编辑/反馈视图都直接更新显隐状态；消息、Toast、悬停等局部反馈动画不参与路由和阶段状态管理。

**主题只有两套规则。** `html[data-theme]` 只取 `light` / `dark`，「跟随系统」由 JS 监听 `matchMedia` 后代写，这样 CSS 不必把深色令牌写两遍。首屏防闪靠 `<head>` 里一段内联脚本在样式表之前定好属性。

## 后端对接

**已经接上真实后端了**（`Dify-Classroom-Interactive-Agent-main`），不再有 mock 开关。
接口清单以 **`apps/API.md`** 为准，前端这边只在 `src/legacy/api.js` 一个文件里发请求。

用到的接口：

| 动作 | 接口 |
| --- | --- |
| 进教室 | `POST /api/session/start`（幂等） |
| 开始上课 | `POST /api/session/{sid}/begin` |
| 视频播完 | `POST /api/session/{sid}/media/done` |
| 下一环节 | `POST /api/session/{sid}/stage/next` |
| 学生发言 | `POST /api/session/{sid}/message` |
| 轮询状态 | `GET /api/session/{sid}/state` |
| 轮询消息 | `GET /api/session/{sid}/messages?since=N` |
| 课堂星级 | `GET /api/session/{sid}/stars` |
| 课后报告 | `GET /api/session/{sid}/export?fmt=json` |

三条容易踩的规矩（都写在 `api.js` 的文件头注释里）：

1. **转录只有一份。** 后端的 `messages` 同时装学生发言和 AI 回复，`POST /message` 的
   `reply_text` 是同一份数据的副本。前端一律以 `GET /messages?since=N` 为唯一事实来源，
   拿 `reply_text` 渲染会让每条回复显示两遍。
2. **阶段推进完全跟随后端。** 前端不判断该切哪一幕，只轮询 `/state` 的 `phase`
   （2 秒一次），变了才切界面；按钮按 `available_actions` 渲染。
3. **不要用后端的 `phase_name`。** 它只覆盖 4 个阶段，`intro` / `ending` 会回退成英文。
   中文词表在前端的 `src/legacy/phases.js`。

会话 id 用的是前端按课时存在 `localStorage` 里的那个 UUID，直接当后端的 `session_id` 传
（后端 `/start` 接受任意 id），两边共用同一个，课后报告才取得到同一节课的数据。

### 视频播放器接入

项目不包含视频文件，也不会创建原生 `<video>`。业务方在进入教学视频阶段前注册播放器：

```js
window.StudentAgentVideoPlayer = {
  mount(container, context) {
    // 使用你们自己的播放器挂载到 container。
    // context.video 是 GET /api/lesson/video 返回的视频信息。
    // 播放结束时必须调用 context.onEnded()。
    const player = createYourPlayer(container, {
      source: context.video,
      startSeconds: context.startSeconds,
      onEnded: context.onEnded,
      onError: context.onError,
    });

    // 页面离开或切换课时时会调用此清理函数。
    return () => player.destroy();
  },
};
```

`context` 还包含当前 `lessonId`。如果播放器脚本在页面初始化后加载，也可以调用 `window.StudentAgentVideoPlayerBridge.register(adapter)` 注册同样的 adapter。

完整的接口契约、请求响应示例、以及后端需要补齐的能力清单，见 **[后端接口说明](docs/api/后端接口说明.md)**。

**想看它运行时一步步发生什么** → [运行时流程](docs/architecture/RUNTIME.md)（24 步）
**想看架构与模块职责** → [前端架构](docs/architecture/ARCHITECTURE.md)
**想看 Next.js 启动、路由、课堂阶段与 API 流程图** → [Next.js 学生端前端流程图](docs/architecture/NEXT_FRONTEND_WORKFLOW.md)（Mermaid，可直接在 Markdown 中预览）

---

## 已知限制

- 后端只配了**一节课**（`ch3-process-scheduling`），所以目录里只有它。多课程 / 多周次要等后端下发目录。
- **阶段 2、3 是一问一答**。后端没有「结构化复述反馈」和「三视角点评」这两个接口，所以那两个面板比早期 mock 版简化了 —— 题由后端抛，学生答，AI 给反馈并判星。
- **课堂讨论阶段不会出现**。`lesson-data/lesson-plan.json` 里 `class_discussion` 是 `enabled: false`；后端也没有多人结构（`student_id` 全链路硬编码，没有班级/讨论组），所以 mock 里的「同学发言 / 老师追问」已去掉。
- **老师按钮现在长在学生页上**：「开始上课 / 视频播完 / 下一环节」按 `available_actions` 渲染。单机演示够用；真实课堂应该由老师页面（`/`）或后端事件推送来触发。
- 视频播放器和视频数据需由业务方接入，未接入时显示挂载占位。
- 星级的**判定粒度**、5 星考核入口、跨课时累积规则在后端都还是预留状态（见 `rules/interaction/MASTERY-STAR-RULES.md`），前端不自行计算，只显示后端给的结果。
