# 前端架构与运行流程

学生端 AI 课堂前端，现运行于 **Next.js App Router + React**。课堂交互位于 Client Component，原有阶段状态机暂存于 `src/legacy` 兼容层。

完整的启动、Hash 路由、课堂阶段和 API 流程图见 [Next.js 学生端前端流程图](NEXT_FRONTEND_WORKFLOW.md)。本文中的 Mermaid 图直接嵌入 Markdown，不依赖已删除的旧 SVG。

**前端是块显示屏，后端是导演。** 演到哪一幕由后端的 `host_phase` 决定，前端只负责把它显示出来。

教学模型是「一节课 3 个阶段」：引导学习 → 总结复述 → 深入思考。

---

## 技术选型

| | 本项目 |
| --- | --- | --- |
| UI | React Client Component + 现有课堂兼容层 |
| 路由与构建 | Next.js App Router / Turbopack |
| 启动 | `npm ci` 后执行 `npm run dev`，Windows 可双击 `启动演示.cmd` |
| 部署 | `npm run build` 后由 Next.js 启动或平台托管 |

迁移阶段优先保持课堂行为等价：Next.js 负责入口、布局、全局样式与生产构建，`src/legacy` 保留已经验证过的阶段推进与 Mock API。后续可以按阶段替换为 React 组件，而无需改动后端契约。

---

## 一、分层架构

依赖关系**单向向上**。`ui.js` 和 `phases.js` 没有任何依赖，只有 `app.js` 认识所有模块。

```mermaid
graph BT
    subgraph L1["基础层 · 无依赖"]
        UI["ui.js<br/>元素构造 / 转义 / DOM 辅助"]
        PH["phases.js<br/>阶段词表"]
    end

    subgraph L2["能力层"]
        API["api.js<br/>★ 全部后端接口 + mock"]
        THEME["theme.js<br/>浅色 / 深色 / 跟随系统"]
    end

    subgraph L3["业务层 · 互不认识"]
        SC["stage-class<br/>课前 / 对话 / 视频"]
        SS["stage-summary<br/>总结复述"]
        SR["stage-reflect<br/>深入思考"]
        SDO["stage-done<br/>结束态"]
        VR["view-review<br/>课后"]
    end

    subgraph L4["编排层"]
        APP["app.js<br/>路由 + 界面跟随 host_phase"]
    end

    L1 --> L2
    L2 --> L3
    L3 --> L4

    style API fill:#ffe6e6,stroke:#c00
    style APP fill:#e6f0ff,stroke:#06c
```

**两条关键设计**：

1. **各阶段模块之间互不认识。** `stage-summary` 不知道 `stage-reflect` 存在 —— 它们只跟 `ctx`（app.js 传进去的接口）打交道。**加一个新阶段不用改任何现有阶段模块。**
2. **所有后端调用都收在 `api.js`。** 各模块只 import 函数，不写 URL。换后端只动这一个文件。

---

## 二、一次课堂的完整流程

```mermaid
sequenceDiagram
    autonumber
    participant S as 学生
    participant F as 前端
    participant B as 后端编排器

    Note over F,B: 前端启动
    B-->>F: GET /api/lesson<br/>返回课时信息
    F->>F: setStage("idle")<br/>显示课前卡片

    Note over S,B: 开课
    S->>F: 点「开始上课」
    F->>B: POST /api/chat<br/>"/上课开始"
    B-->>F: hostPhase = "intro"<br/>introComplete = true
    F->>F: applyServerTurn()<br/>切到对话界面
    F-->>S: 显示课程介绍 +<br/>「开始播放教学视频」按钮

    Note over S,B: 看视频（前端局部状态，不经后端）
    S->>F: 点「开始播放教学视频」
    F->>F: setStage("video")<br/>本地切换，不发请求
    F-->>S: 播放视频

    Note over S,B: 视频结束 → 通知后端
    S->>F: 视频播完（ended 自动）<br/>或点「看完了」（手动）
    F->>B: POST /api/chat<br/>"/视频结束"
    B-->>F: hostPhase = "recap_discussion"
    F->>F: setStage("summary") 立即切换
    F-->>S: 总结复述对话框

    Note over S,B: 阶段 2 → 3
    S->>F: 写完总结，提交
    F->>B: POST /api/summary/review
    B-->>F: 结构化反馈
    F-->>S: AI 反馈消息
    S->>F: 点「进入下一阶段」
    F->>B: POST /api/chat "/继续"
    B-->>F: hostPhase = "deep_inquiry"
    F->>F: setStage("reflect") 立即切换

    Note over S,B: 阶段 3 → 结束
    S->>F: 在对话框答完三个视角 → 点「结束本节课」
    F->>B: POST /api/chat "/下课"
    B-->>F: hostPhase = "ending"
    F-->>S: 结束态 + 知识点清单
```

**注意每一步的模式都一样**：前端发一句话 → 后端返回 `hostPhase` → 前端比对 → 变了才切。

---

## 三、界面状态机

界面由 `host_phase` 映射得到，但**视频是前端唯一的局部状态**（同一幕内部的第二屏）。

```mermaid
stateDiagram-v2
    direction TB

    [*] --> 课前

    课前 --> 对话 : hostPhase = intro
    对话 --> 视频 : 学生点「播放视频」<br/>（前端局部切换，不经后端）
    视频 --> 总结对话 : hostPhase = recap_discussion
    总结对话 --> 思考对话 : hostPhase = deep_inquiry
    思考对话 --> 结束态 : hostPhase = ending
    结束态 --> [*]

    note right of 视频
        前端唯一的局部状态
        后端只知道 guided_learning
        不知道学生在看没看视频
    end note
```

**为什么视频是局部状态**：后端的 `guided_learning` 这一幕本身就包含「讲课 + 看视频」两段，视频是它内部的事。学生点播放时前端自己切，播完**才**通知后端。

---

## 四、核心机制：`applyServerTurn()`

整个「完全跟随」就落在这一个函数里。**每次拿到后端响应都会走一遍。**

```mermaid
flowchart TD
    A["收到后端响应"] --> B{"有 hostPhase 吗？"}
    B -->|没有| Z["什么都不做"]
    B -->|有| C{"前端认识这个值吗？"}

    C -->|不认识| Y["控制台警告<br/>不动界面"]
    C -->|认识| D{"和当前相同吗？"}

    D -->|相同| Z
    D -->|不同| E["更新 hostPhase<br/>更新右上角状态胶囊"]

    E --> F{"已经在目标界面了吗？"}
    F -->|是| G["只更新状态文字<br/>（比如正在看视频）"]
    F -->|否| I["直接切换到目标界面<br/>不播放切换动画"]

    style Z fill:#f5f5f5,stroke:#999
    style Y fill:#fff0e0,stroke:#e90
    style I fill:#e6f0ff,stroke:#06c
```

几个分支都有理由：

| 分支 | 为什么 |
| --- | --- |
| **不认识的值** | 后端将来加新阶段时，旧前端不会崩，只少显示一幕 |
| **已经在目标界面** | 视频是 `guided_learning` 的内部状态，别把学生正在看的视频打断 |
| **目标发生变化** | 直接更新 Stage 显隐，不等待动画，不阻塞后续响应 |

---

## 五、模块清单

| 文件 | 职责 |
| --- | --- |
| `src/app/layout.js` | Next.js 根布局、元数据和主题首屏防闪 |
| `src/app/page.js` | `/` 路由入口 |
| `src/app/globals.css` | 全局设计系统 |
| `src/components/StudentApp.js` | 课堂 Client Component 边界 |
| `src/components/legacyMarkup.js` | 迁移期间保留的页面结构 |
| `src/legacy/api.js` | **全部后端接口 + mock** |
| `src/legacy/app.js` | 编排层：路由 + 界面跟随 `host_phase` |
| `src/legacy/stage-*.js` | 各课堂阶段的现有交互逻辑 |
| `src/legacy/theme.js` | 浅色 / 深色 / 跟随系统 |
| `src/legacy/phases.js` | `host_phase` 与界面的唯一映射 |

### 阶段模块的统一契约

阶段模块通过统一的工厂函数接收 `ctx`；按需实现以下方法，`enter`、`leave`、`reset` 并非每个模块都必须具备：

```js
export function createStage(ctx) {
  return {
    mount(),          // 可选：首次挂载时绑定事件，只调一次
    enter(stageName), // 可选：进入该界面时更新内容
    leave(),          // 可选：退出时清理资源
    reset()           // 可选：重置模块状态
  };
}
```

`ctx` 是 app.js 注入的接口，提供 `sessionId` / `getLesson()` / `applyServerTurn()` / `sendControl()` / `setStatus()` 等。

---

## 六、与后端的关系

```mermaid
graph LR
    subgraph FE["前端（显示器）"]
        UI2["界面渲染"]
        ST["状态胶囊"]
        VL["即时界面切换"]
    end

    subgraph BE["后端（导演）"]
        JA["judge_advance<br/>决定什么时候切幕"]
        TK["tick<br/>真实时钟结算"]
        PS["阶段内容<br/>stages/*"]
    end

    JA -- "hostPhase" --> FE
    FE -- "控制消息" --> JA

    TK -.驱动.-> JA
    PS -.驱动.-> JA
```

四类接口、四条控制消息：

| 控制消息 | 什么时候发 | 期望后端行为 |
| --- | --- | --- |
| `/上课开始` | 学生点「开始上课」 | 进 `intro`，返回课程介绍 |
| `/视频结束` | 视频播完，或点「看完了」 | 进 `recap_discussion` |
| `/继续` | 学生点「进入下一阶段」 | 由 `judge_advance` 判定是否推进 |
| `/下课` | 学生点「结束本节课」 | 进 `ending`，返回收尾发言 |

**「学生手动进入下一阶段」保留着，但推不推由后端决定** —— 前端只负责发请求、然后跟随 `hostPhase`。

后端的实现在 `ORCHESTRATOR.md`：它用**真实墙上时钟**判断该不该切幕（每幕有预算时长，`tick` 算真实耗时，`judge_advance` 按「耗时 + 证据 + 老师配的策略」判定）。**前端完全不需要知道这些细节。**

**`sessionId` 是后端 checkpointer 的 `thread_id`**，前端已改成持久化存储（`localStorage`），刷新页面沿用同一个，这样后端才能从上一轮状态恢复。

---

## 七、演示顺序建议

| 步骤 | 展示什么 |
| --- | --- |
| 1. 选课 | 展示课程卡、进入课程并选择已上过或本周课时，右上角可切换外观 |
| 2. 课时入口 | 已上过的课进入课后，本周尚未上过的课进入课堂；未来周次不可进入 |
| 3. 开始上课 | 状态胶囊变「课程介绍」，AI 返回介绍 |
| 4. 播放视频 | 外部播放器挂载到预留容器，完成后调用 `onEnded()` |
| 5. 阶段切换 | 展示 `hostPhase` 变化后界面立即更新 |
| 6. 总结复述 | 在固定对话框中发送总结、查看 AI 反馈消息 |
| 7. 深入思考 → 结束态 | 三个视角按顺序在对话框中进行 |

想强调「前端跟随后端」的话，**打开网络面板** —— 每次切幕前都有一个 `/api/chat` 请求，`hostPhase` 就在响应里。

---

## 附：本地启动

```bash
npm install
npm run dev                  # → http://localhost:3000
```

接口契约、请求响应示例、后端需要补齐的能力清单，见 [后端接口说明](../api/后端接口说明.md)。
