# Next.js 学生端前端流程图

> 现状：Next.js App Router 只有 `/` 一个文件路由；课程、周次、课时、课堂和课后由浏览器 Hash 路由控制。课堂内的阶段由后端响应中的 `hostPhase` 决定，当前 `src/legacy/api.js` 默认使用 Mock。

## 1. 启动、渲染与客户端初始化

```mermaid
flowchart TD
    A[访问 /] --> B[Next.js 执行 RootLayout]
    B --> C[主题首屏脚本读取本地偏好]
    B --> D[加载 globals.css]
    B --> E[page.js 渲染 StudentApp]
    E --> F[服务端输出课程目录、周次、课时入口、课堂、课后的初始 HTML]
    F --> G[浏览器显示页面并完成 React hydration]
    G --> H[StudentApp 的 useEffect 动态导入 legacy/app.js]
    H --> I[创建主题控制器和各阶段模块]
    I --> J[按课时读取或生成 sessionId 并保存到 localStorage]
    J --> K[每个唯一模块 mount 一次，绑定事件]
    K --> L[注册 hashchange 并执行 renderRoute]
    L --> M[获取课程目录并验证 Hash 路由]
    M --> N[显示课程、周次、课时入口、课堂或课后]
```

`src/app/layout.js` 负责布局、元数据、主题首屏脚本和全局 CSS；`src/app/page.js` 渲染 `StudentApp`。`StudentApp` 是 Client Component，保留现有页面结构，并在挂载后导入 `src/legacy/app.js`。初始 HTML 不等于课堂业务已加载；业务事件绑定发生在动态导入之后。

## 2. 选课程、选周次与路由守卫

```mermaid
flowchart TD
    A[访问 / 或 #] --> B[GET /api/student/courses]
    B --> C[只显示学生已选课程]
    C --> D[点击课程卡]
    D --> E[进入 #/course/:courseId]
    E --> F[筛选 completed 与 current 的课时]
    F --> G[显示已上过周次与本周课时]
    G --> H[点击某周课时]
    H --> I[进入 #/lesson/:courseId/:lessonId]
    I --> J[按 lessonId 建立独立 sessionId]
    J --> K{课时 status}
    K -->|current| L[只显示课堂入口，进入 #/class/:courseId/:lessonId]
    K -->|completed| M[只显示课后入口，进入 #/review/:courseId/:lessonId]
    N[直接输入深链接] --> O{课程与课时存在且 status 可学?}
    O -->|否| P[返回课程目录或该课程周次页]
    O -->|是| I
```

演示模式展示高等数学、线性代数、通信原理、操作系统各 16 周；以 2026-09-01 为学期起点推算当前周，之前周次假定已上过。与课时状态不匹配的课堂或课后直达链接会返回该课时入口；课堂结束后，当前页面将该课时切换为已完成。正式接入时，`status` 应取自后端真实授课与发布状态，前端过滤与深链接守卫只是用户体验保护，后端仍须做权限校验。

## 3. 进入课堂与四阶段教学流程

```mermaid
flowchart TD
    A[进入 #/class/:courseId/:lessonId] --> B{课时 lesson 已缓存?}
    B -->|否| C[显示 idle，禁用开始按钮]
    C --> D[fetchLesson 获取课程信息]
    D -->|成功| E[填充课时卡片并启用开始按钮]
    D -->|失败| F[显示错误并弹出 Toast]
    B -->|是| G[恢复 currentStage]
    E --> H[点击开始上课]
    H --> I[sendChat：/上课开始]
    I --> J[hostPhase = intro]
    J --> K[chat：课程介绍与 AI 对话]
    K --> L[点击播放教学视频]
    L --> M[前端局部切到 video 并获取视频信息]
    M --> N{视频结束方式}
    N -->|自然播放完| O[发送 /视频结束]
    N -->|手动点击看完了| O
    O --> P[hostPhase = recap_discussion]
    P --> Q[summary：在对话框中发送总结]
    Q --> R[reviewSummary 返回结构化反馈消息]
    R --> S{学生选择}
    S -->|我再改一版| Q
    S -->|进入下一阶段| T[发送 /继续]
    T --> U[hostPhase = deep_inquiry]
    U --> V[reflect：在对话框中依次回答三个视角]
    V --> W[submitReflection 返回点评消息]
    W --> X{三个视角完成?}
    X -->|否| V
    X -->|是| Y[发送 /继续]
    Y --> Z[hostPhase = class_discussion]
    Z --> AA[discuss：加载题目和讨论消息]
    AA --> AB[学生发言，显示讨论反馈]
    AB --> AC[点击结束本节课，发送 /下课]
    AC --> AD[hostPhase = ending]
    AD --> AE[done：结束态和知识点清单]
    AE --> AF[点击去看看掌握情况，进入当前课时的 #/review/:courseId/:lessonId]
```

图中 `hostPhase` 表示服务端响应的权威状态；默认 Mock 会模拟同样的字段。真实后端是否推进阶段由后端决定，前端的“继续”按钮只发控制消息。`chat → video` 是 `guided_learning` 内的前端局部切换，点击播放时不发送阶段推进请求；视频结束后才通知后端。

## 4. `hostPhase` 到课堂界面的映射与判定

| `hostPhase` | `uiOf()` 目标 | 学生看到的界面 |
| --- | --- | --- |
| `uninitialized` | `idle` | 课前卡片 |
| `intro` | `chat` | 课程介绍/对话 |
| `guided_learning` | `chat` | 引导学习对话；视频是局部状态 |
| `recap_discussion` | `summary` | 总结复述 |
| `deep_inquiry` | `reflect` | 深入思考 |
| `class_discussion` | `discuss` | 课堂讨论 |
| `ending` | `done` | 课程结束 |

```mermaid
flowchart TD
    A[收到含业务结果的 API 响应] --> B{有 hostPhase?}
    B -->|否| C[只处理业务结果]
    B -->|是| D{isKnown?}
    D -->|否| E[记录警告，保持当前界面]
    D -->|是| F{与已保存的 hostPhase 相同?}
    F -->|是| G[不重复切换]
    F -->|否| H[保存 hostPhase 并更新页头状态]
    H --> I[uiOf 映射目标 Stage]
    I --> J{目标已是 currentStage?}
    J -->|是| K[保留当前界面]
    J -->|否| L{guided_learning 且正在看 video?}
    L -->|是| M[保留视频播放]
    L -->|否| N[setStage：隐藏其他 Stage，显示目标]
    N --> O[调用目标 owner.enter]
```

这里的 `applyServerTurn()` 只处理阶段变化。总结反馈、反思点评、讨论消息等各阶段的业务内容由对应模块分别渲染。页面和 Stage 切换均为即时显隐；课堂聊天、总结复述、深入思考与课堂讨论使用固定尺寸的对话面板，消息在面板内滚动。消息、Toast、悬停等局部反馈动画仍保留。

## 5. API 与错误路径

| 请求 | 触发点 | 用途 |
| --- | --- | --- |
| `GET /api/student/courses` | 首次打开课程目录 | 学生已选课程、可学周次及授课状态 |
| `GET /api/lesson` | 首次进入课堂 | 课时信息 |
| `POST /api/chat` | 开课、提问、视频结束、继续、下课 | AI 回复与 `hostPhase` |
| `GET /api/lesson/video` | 点击播放视频 | 视频地址和元数据 |
| `POST /api/summary/review` | 提交总结 | 结构化反馈 |
| `POST /api/reflection` | 提交思考卡 | 点评与追问 |
| `GET /api/discussion` | 首次进入讨论 | 题目与消息 |
| `POST /api/discussion` | 学生发言 | 新消息 |

完整字段契约和预留接口见 [后端接口说明](../api/后端接口说明.md)。真实后端接入时将 `src/legacy/api.js` 的 `USE_MOCK` 置为 `false`，并在根目录 `.env.local` 配置 `NEXT_PUBLIC_API_BASE_URL`；该变量属于公开的浏览器端配置，不可存放密钥。

## 6. 文档维护边界

- 修改 Next.js 入口或 Hash 路由时，同步更新第 1、2 节。
- 修改 `src/legacy/phases.js` 或 `applyServerTurn()` 时，同步更新第 3、4 节。
- 修改 `src/legacy/api.js` 或阶段模块的请求时，同步更新第 5 节。
- 不再维护旧的独立 SVG/HTML 导出，避免图像与代码、Markdown 文档出现两个版本。
