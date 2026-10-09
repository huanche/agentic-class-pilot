# Implementation Plan: 更换"加入课程"页面视觉

**Branch**: `001-join-course-page`(特性 ID;按团队现行约定在 `lzm` 分支开发) | **Date**: 2026-10-09 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-join-course-page/spec.md`

## Summary

将平台前端 `/join` 路由页面从"布局内嵌的 shadcn 单卡片表单"更换为**沉浸式全屏选课页**,视觉基准为学生学习空间(学生 Agent)的选课/登录遮罩设计(全屏柔光遮罩 + 居中 380px 玻璃卡片 + 图标徽章 + 入场动画)。选课业务逻辑(8 位选课码、`EnrollmentsService.joinCourse`、成功跳转、my-courses 刷新)、路由地址与全部入口**保持不变**;实现方式为在 platform 前端内以 Tailwind + 主题 token 重建视觉,**不跨服务引用学生 Agent 代码**。

## Technical Context

**Language/Version**: TypeScript + React(TanStack Router/Query),Vite 构建

**Primary Dependencies**: Tailwind CSS、shadcn/ui(Radix)、react-hook-form + zod(现有,保留)、lucide-react

**Storage**: N/A(无数据模型变更;沿用现有 enrollments 接口)

**Testing**: Playwright(`platform/frontend` 下 `bunx playwright test`,现有 tests/ 目录含 login/join 相关基建);Biome lint

**Target Platform**: 桌面浏览器,经统一入口 `http://localhost:8088` 访问(生产为对应域名)

**Project Type**: web-app 前端呈现层改造(单路由页面重写)

**Performance Goals**: 页面为纯静态呈现 + 一次既有接口调用,无新增性能预算;入场动画 0.5s 不阻塞交互

**Constraints**: 路由 `/join` 不变;不新增依赖;不改后端;学生 Agent 零改动

**Scale/Scope**: 1 个路由文件重写 + 1 个 e2e 用例文件新增

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 结论 | 说明 |
|---|---|---|
| I. 服务边界自治 | ✅ 通过 | 仅复制视觉语言(Tailwind 重建),不 import 学生 Agent 代码、不读写其文件;改动全部收敛在 `platform/` |
| II. 统一入口与可信会话 | ✅ 通过 | 页面经 8088 入口与既有 `_layout` 鉴权访问;不新增直连路径 |
| III. 密钥与凭证不入库 | ✅ 不涉及 | 无新增配置 |
| IV. 仓库即唯一事实源 | ✅ 通过 | 改动全部入库走评审,无容器热修 |
| V. 先验证后发布 | ✅ 通过 | 计划内置:src 变更后执行 platform 前端构建;8088 端到端验证 + Playwright 用例 |
| VI. Git 流程与产物卫生 | ✅ 通过 | 在 lzm 分支开发(现行特性分支约定);无构建产物入库;提交走 conventional 前缀 |

Phase 1 设计后复查:无新增违规(见 Complexity Tracking——为空)。

## Project Structure

### Documentation (this feature)

```text
specs/001-join-course-page/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/
│   └── ui-join-page.md  # Phase 1 output:页面行为契约
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
platform/frontend/
├── src/
│   ├── routes/
│   │   └── _layout/
│   │       └── join.tsx      # 重写:沉浸式全屏选课页(本特性唯一源码改动)
│   └── components/ui/        # 复用现有 shadcn 组件(Input/Button/Form),不新增组件
└── tests/
    └── join.spec.ts          # 新增:加入课程页 e2e(视觉关键断言 + 成功/失败/防重复流程)
```

**Structure Decision**: 单文件呈现层重写。全屏覆盖层、柔光背景、玻璃卡片、图标徽章、入场动画全部以 Tailwind 任意值/局部样式收敛在 `join.tsx` 内,不新增组件文件、不动 `routeTree.gen.ts`(路由注册不变)、不动侧栏与入口链接。

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

无违规,留空。
