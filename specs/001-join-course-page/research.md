# Research: 更换"加入课程"页面视觉

**Date**: 2026-10-09 | **Status**: 完成(全部未知项已解决)

> 依据:specify 阶段对两侧代码的直接调研 + 学生端 `globals.css` 视觉参数提取。

## D1: 视觉实现方式 —— 在 platform 内用 Tailwind 重建

**Decision**: 在 `platform/frontend` 内以 Tailwind 任意值/局部样式 + 平台主题 token(酒红 #B00055 体系)重建该视觉,收敛在 `join.tsx` 单文件。

**Rationale**: 两端技术栈不同(学生端为手写 CSS + 自有 CSS 变量 `--brand-soft` 等,平台为 Tailwind + shadcn);宪法 I 禁止跨服务引代码,复制 CSS 文件会引入不通的 token 体系并形成双份维护。

**Alternatives considered**:
- 整段拷贝学生端 CSS(拒绝:token 不通、风格割裂、双份维护)
- 跳转/嵌入学生端页面(拒绝:破坏统一入口与平台鉴权;两端选课逻辑不同)

## D2: 全屏沉浸的实现 —— _layout 内渲染 fixed 覆盖层

**Decision**: `/join` 路由保持注册在 `_layout` 下不动,组件渲染 `fixed inset-0` 高层级覆盖层盖住侧栏,形成全屏沉浸效果。

**Rationale**: 保住既有鉴权上下文、路由注册(`routeTree.gen.ts` 零改动)与全部入口;改动半径最小。

**Alternatives considered**:
- 路由移出 `_layout`(拒绝:需自建鉴权守卫、改路由树,风险大收益零)
- 仅放大居中卡片不覆盖全屏(拒绝:不满足 FR-001"沉浸式全屏"基准)

**注意项(实现时核对)**: 学生端覆盖层 z-index=400(toast 300 之上)。平台端 toast 层级不同,实现时需确认成功提示不被覆盖层遮挡;因成功即跳转课程页,toast 也可由跳转后页面承载。

## D3: 表单与提交逻辑 —— 保留既有逻辑,只换呈现

**Decision**: 保留 react-hook-form + zod(非空/长度规则不动)+ `EnrollmentsService.joinCourse` mutation + onSuccess(toast 含课程名 → invalidate `my-courses` → 跳转课程页)。错误呈现改为**卡片内内联中文错误**,输入值保留、焦点回输入框;同时把现有 `onError: handleError.bind(showErrorToast)` 这种可疑用法在重写时修正为正确调用。

**Rationale**: FR-006 要求选课能力与规则不变;FR-003 要求内联错误+保留输入+回焦点,纯 toast 不满足。

**Alternatives considered**: 维持纯 toast 错误(拒绝:见上)。

## D4: 输入与引导细节

**Decision**: 输入框沿用 `uppercase font-mono tracking-widest maxLength=8`;卡片底部**常驻**引导文案"还没有选课码?找任课老师要一个"(学生端 required 模式同款)。

**Rationale**: 平台的加入课程页是独立入口页,语境等同学生端 required(无退路),常驻引导最贴合;US2 场景 4 要求可见。

## D5: 视觉参数基准(自学生端 `globals.css` 提取,映射到平台)

| 元素 | 学生端参数 | 平台映射 |
|---|---|---|
| 覆盖层 | `fixed inset-0` z-400,flex 居中,padding 24px,页面底色 | 同布局,z 值实现时核对 |
| 柔光背景 | `radial-gradient(ellipse 70% 50% at 50% 0%, var(--brand-soft) → transparent 70%)`,pointer-events:none | 酒红低透明度(约 8%~12%)同形渐变 |
| 卡片 | max-width 380px,padding 32px,1px 边框,大圆角,`backdrop-blur(20px) saturate(1.3)`,悬停级阴影 | `backdrop-blur-[20px] saturate-[1.3]` 等 Tailwind 任意值 |
| 图标徽章 | 56×56 圆形,brand-soft 底,28px 学位帽 SVG | 同款学位帽图形(线性 1.5 描边) |
| 标题/副标题 | 19px/600 与 13px muted,居中 | 同参数 |
| 入场动画 | `opacity 0→1; translateY(16px)→0; scale(.97)→1; 0.5s ease-out` | 局部 keyframes 复刻 |

**Alternatives considered**: 去掉入场动画做纯静态(拒绝:基准页含该动效,视觉一致性应包含)。

## D6: 验证策略

**Decision**: 新增 Playwright 用例 `platform/frontend/tests/join.spec.ts`:入口可达、全屏关键元素存在、无效码内联错误+输入保留、防重复提交;"有效码成功加入"依赖动态课程 fixture,视 `tests/config.ts` 既有基建决定自动化深度,兜底人工走查(见 quickstart.md)。`src` 变更后执行平台前端构建(tsc + vite build),8088 端到端验收。

**Rationale**: 宪法 V;平台已有 Playwright 基建与登录 setup 可复用。

## D7: 分支与提交

**Decision**: 在 `lzm` 分支开发(团队现行特性分支约定,宪法 VI);spec 目录名 `001-join-course-page` 作为特性 ID;提交用 `feat(platform): ...` 前缀。
