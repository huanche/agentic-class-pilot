---
description: "Task list for feature implementation"
---

# Tasks: 更换"加入课程"页面视觉

**Input**: Design documents from `/specs/001-join-course-page/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ui-join-page.md ✅, quickstart.md ✅

**Tests**: spec US3 与 quickstart.md 明确要求 e2e 与人工走查,故包含测试任务。

**Organization**: 按用户故事分组。本特性为**单文件呈现层重写**(`platform/frontend/src/routes/_layout/join.tsx` + 新增 e2e),同文件任务严格串行,无 [P] 并行任务。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行(不同文件、无依赖)——本特性无
- **[Story]**: 所属用户故事(US1/US2/US3)

## Path Conventions

- Web app:`platform/frontend/src/`(源码)、`platform/frontend/tests/`(e2e)

---

## Phase 1: Setup

**Purpose**: 基线确认

- [x] T001 确认开发基线:在 `lzm` 分支、`git fetch` 同步远端(宪法 VI);明确本特性改动仅限 `platform/frontend/src/routes/_layout/join.tsx`、`platform/frontend/tests/join.spec.ts`、`specs/001-join-course-page/` 三处,与工作区既有 WIP(学生端播放器适配等)严格隔离

## Phase 2: Foundational

**Purpose**: 无——单文件呈现层改动,无共享基建前置,Setup 后直接进入 US1。

---

## Phase 3: User Story 1 - 全屏选课页替换现有表单页 (Priority: P1) 🎯 MVP

**Goal**: `/join` 呈现沉浸式全屏选课页(学生端视觉语言),成功路径行为不变

**Independent Test**: 学生账号经 8088 点侧栏"加入课程"→ 全屏新视觉;有效码加入 → 成功提示 + 跳转课程页(spec US1 验收场景 1-3)

### Implementation for User Story 1

- [x] T002 [US1] 重写覆盖层骨架:`platform/frontend/src/routes/_layout/join.tsx` —— 路由注册 `/_layout/join` 与页面 meta 保持不动;组件渲染 `fixed inset-0` 全屏覆盖层(层级高于侧栏;实现时核对平台 toast z 层级,参照学生端约定覆盖层 400 > toast 300,确保成功提示不被遮挡),flex 水平垂直居中、padding 24px;柔光背景层:`radial-gradient(ellipse 70% 50% at 50% 0%, 酒红 #B00055 低透明度约 8%~12% → transparent 70%)`、`pointer-events-none`(参数引自 specs/001-join-course-page/research.md D5 表);卡片:`max-w-[380px]`、`p-8`(32px)、1px 边框、大圆角、`backdrop-blur-[20px] saturate-[1.3]`、阴影;入场动画(局部 keyframes):`opacity 0→1`、`translateY(16px)→0`、`scale(.97)→1`、0.5s ease-out,仅入场一次且不阻塞交互
- [x] T003 [US1] 卡片内容(同文件,依赖 T002):56px 圆形徽章(酒红柔光底)内嵌 28px 学位帽 SVG(strokeWidth 1.5,与学生端同款图形);标题"加入课程"(约 19px/600,居中);副标题"输入教师分享的 8 位选课码"(约 13px muted,居中);选课码输入框:自动大写、等宽字体、宽字距、maxLength 8(约束引自 specs/001-join-course-page/data-model.md:"8 位标识,输入侧统一大写、去空格、上限 8 位"),进入页面 autofocus;提交按钮"加入课程";卡片底部常驻引导文案"还没有选课码?找任课老师要一个"
- [x] T004 [US1] 接入既有业务逻辑(同文件,依赖 T003):保留既有 zod schema 与校验规则原样(不新增不收紧);保留 `EnrollmentsService.joinCourse` mutation;onSuccess:`showSuccessToast`(含课程名)→ `invalidateQueries("my-courses")` → 跳转该课程页——三步与更换前完全一致(spec FR-005/FR-006)

**Checkpoint**: 全屏新页面可用,成功路径与更换前一致——独立可验收的 MVP

---

## Phase 4: User Story 2 - 输入与反馈体验 (Priority: P2)

**Goal**: 错误内联呈现、焦点管理、防重复提交、无码引导

**Independent Test**: 输入小写→自动大写;无效码→内联中文错误+输入保留+焦点回框;连点提交→仅一次请求(spec US2 验收场景 1-4)

### Implementation for User Story 2

- [x] T005 [US2] 内联错误与焦点管理(同文件,依赖 T004):`onError` 改为卡片内内联中文错误(替换现有 `handleError.bind(showErrorToast)` 用法为语义正确的调用,toast 可保留但以内联为主),错误后输入值保留、焦点自动回到输入框;错误文案取后端 detail,兜底友好中文默认;错误区带 `role="alert"`/aria-live(对照 specs/001-join-course-page/contracts/ui-join-page.md 交互契约)
- [x] T006 [US2] 提交中状态与可重试(同文件,依赖 T005):提交进行中按钮 loading 且 disabled(复用 LoadingButton,确认在覆盖层内可用),重复点击不产生重复请求;网络失败/超时展示可重试错误且不丢输入

**Checkpoint**: 输入反馈体验达标,页面"好看"之外"好用"

---

## Phase 5: User Story 3 - 入口与行为一致性回归 (Priority: P3)

**Goal**: e2e 固化回归 + 构建校验,证明入口一致、能力无回归

**Independent Test**: `bunx playwright test join.spec.ts` 全绿;平台前端 build 零错误(spec US3 验收场景 1-3)

### Tests & Verification for User Story 3

- [x] T007 [US3] 新增 e2e `platform/frontend/tests/join.spec.ts`(复用既有 `tests/auth.setup.ts` 与 `tests/config.ts` 基建):用例①学生登录→侧栏"加入课程"→ 全屏关键元素存在(徽章/标题/副标题/引导文案/输入框);用例②输入小写字母→呈大写;用例③无效码提交→内联中文错误且输入值保留;用例④快速连点提交→网络层仅一次 join 请求;"有效码成功加入"若课程 fixture 基建允许则纳入,否则在用例注释标注由人工走查覆盖(quickstart.md 第 2 步)
- [x] T008 [US3] 构建校验(宪法 V):在 `platform/frontend` 执行 build 脚本(`tsc -p tsconfig.build.json && vite build`),类型与构建零错误;确认无构建产物混入待提交范围

**Checkpoint**: 全部用户故事完成,回归有自动化兜底

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 端到端验收与提交卫生

- [ ] T009 按 `specs/001-join-course-page/quickstart.md` 执行 9 步人工走查(统一入口 8088,学生测试账号),结果记录回 quickstart.md 或 PR 描述;重点含 US3-3(学生端选课页不受影响)
  - 2026-10-09 进展:第 1/3/4/5/6/7/9 步已由 e2e(5/5 通过,打在 8088 真实入口)覆盖;第 2 步(有效码加入→提示+跳转)与第 8 步(加入后 my-courses 即时刷新)需要真实选课码,待人工执行
- [x] T010 提交:conventional 前缀,建议 `feat(platform): 加入课程页更换为全屏沉浸式设计(specs/001)`;提交范围仅 `platform/frontend/src/routes/_layout/join.tsx`、`platform/frontend/tests/join.spec.ts`、`specs/001-join-course-page/`;不含工作区 WIP、不含任何构建产物(宪法 VI)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (T001)**: 无前置,立即开始
- **Foundational**: 无此阶段
- **US1 (T002→T003→T004)**: 同文件严格串行;Setup 后即可开始
- **US2 (T005→T006)**: 依赖 US1 完成(同文件增量)
- **US3 (T007→T008)**: 依赖 US1+US2 完成(对最终行为做回归)
- **Polish (T009→T010)**: 依赖全部完成

### Parallel Opportunities

无——本特性收敛在单文件 + 单测试文件,全部任务串行(这正是改动半径小的体现)。

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. T001 基线确认
2. T002→T003→T004 完成全屏页与成功路径
3. **STOP and VALIDATE**: 按 spec US1 验收场景 1-3 走查(8088)
4. 此时可演示:新视觉已上线,能力不变

### Incremental Delivery

US1(MVP)→ US2(体验补强)→ US3(回归固化)→ Polish(验收+提交);任一 Checkpoint 可停可交付。

---

## Notes

- 所有视觉参数以 `specs/001-join-course-page/research.md` D5 表为准
- 行为契约以 `specs/001-join-course-page/contracts/ui-join-page.md` 为准
- 每完成一个任务勾选对应复选框;实现期发现偏差回写 research.md/plan.md 再继续
