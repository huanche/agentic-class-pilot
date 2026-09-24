# AI 教育平台开发结构

本文档定义当前正式平台的代码边界、核心流程和后续开发入口。当前唯一运行入口为：

```text
http://localhost:3100
```

原独立教师端实验工作流 `/teacher-agent` 已停止维护并移除。教师端能力统一从平台首页进入，不再维护第二套页面、API、状态机和发布链路。

## 1. 产品入口与主流程

```text
平台首页 app/page.tsx
  ├─ 主题/材料生成普通课堂
  ├─ 快速生成课件：兼容现有 PPTX / PDF 双路径
  ├─ 完整课程体系 app/course-space/
  │    └─ 课程 → 模块 → 课时 → 材料库 → 教学产物中心
  └─ 导入 PPTX / PDF
       ├─ 高保真还原：保持页数、顺序和原始视觉画布
       └─ AI 增强：Learning Skills 分析、重组和教学增强
            ↓
     generationSession
            ↓
     app/generation-preview/page.tsx
            ↓
     大纲 → 场景内容 → 动作 → TTS/媒体资产
            ↓
     app/classroom/[id]/
```

两条课件转换路径共享 OpenMAIC 的 Scene/Action DSL、资产池、课堂播放引擎和导出能力，避免产生独立播放器或平行数据模型。

完整课程体系位于单课件生成流程之上。上传课程材料只保存并进入解析、审核队列，不直接触发教学大纲或课件生成。教师在教学产物中心选择课程、模块或课时范围，再手动选择要生成的产物。OpenMAIC PBL 是可生成的教学活动类型之一，不替代课程空间与知识库。

## 2. 目录职责

| 目录 | 职责 | 开发约束 |
| --- | --- | --- |
| `app/` | Next.js 页面、路由和服务端 API | 页面只编排交互；可复用业务逻辑下沉到 `lib/` |
| `app/api/generate/` | 大纲、场景、动作、TTS 等生成接口 | API 保持输入校验、Provider 调用和统一错误边界 |
| `app/generation-preview/` | 生成预览、审核和进入课堂 | 两条导入路径最终汇合到这里 |
| `app/classroom/[id]/` | OpenMAIC 课堂播放入口 | 使用 Scene/Action 运行时，不新建 PPT 播放器 |
| `app/course-space/` | 完整课程体系教师工作台 | 首版使用默认教师身份，数据契约保留多教师和多课程字段 |
| `lib/course-space/` | 课程、模块、课时、材料和产物任务领域模型 | 通过 Repository 隔离浏览器首版存储与后续服务端存储 |
| `app/api/course-space/` | 课程体系教师端 API | 课程、上传、解析、后台生成、审核和发布统一入口 |
| `app/api/student/courses/` | 学生智能体只读知识 API | 只返回当前已发布知识包，不暴露草稿和待审核内容 |
| `lib/server/course-space-storage.ts` | 课程空间服务端仓储 | 原材料、SHA-256、Job、审核产物和知识包版本化落盘 |
| `lib/server/course-material-parser.ts` | 显式材料解析任务 | 保留页码、公式与来源分块；PPTX 支持本地 OOXML 解析 |
| `lib/server/course-artifact-runner.ts` | 教学产物后台执行器 | AI/OpenMAIC 生成；外部模型故障时降级为可追溯审核草稿 |
| `components/generation/` | 课件模式选择、PPT 内容审核等生成 UI | 只放生成流程专用组件 |
| `lib/import/` | PPTX/PDF 导入和课程上下文构建 | 保留页码、标题、正文、备注及视觉来源信息 |
| `lib/learning-skills/` | K12 Learning Skills 适配与 AI 增强 | 与高保真路径解耦，通过明确模式选择启用 |
| `lib/course-governance/` | 来源指纹、场景来源、降级记录和发布门禁 | 所有 PPT/PDF 转换课程必须持久化治理记录 |
| `components/governance/` | 教师逐场景审核与发布状态界面 | 场景修改后必须重新审核 |
| `lib/hooks/use-scene-generator.ts` | Scene、Action、TTS 和资产生成编排 | 是前端生成链路的主要汇合点 |
| `lib/orchestration/` | LangGraph 多智能体编排 | 负责生成协作，不承担课堂渲染 |
| `lib/playback/` | Action 顺序执行、自动播放和互动控制 | 所有课堂播放行为统一从这里扩展 |
| `lib/audio/`、`lib/media/` | Qwen3 TTS、音频解析与共享资产池 | `SpeechAction.audioId` 是生成与播放的连接点 |
| `lib/store/`、`lib/utils/database.ts` | Zustand 设置与 IndexedDB 持久化 | 新状态优先进入现有 store/数据库结构 |
| `packages/@openmaic/*` | DSL、Importer、Renderer、Storage、Editor 等基础包 | 平台能力优先复用包，不在应用层复制实现 |
| `skills/ai-education-courseware/` | AI 教育平台可安装 Skill | 与平台 API/数据契约保持同步 |
| `tests/`、`e2e/` | 单元、集成和浏览器测试 | 新功能至少覆盖模式分流和关键数据契约 |
| `scripts/` | 构建、同步和维护脚本 | 不在脚本中复制业务逻辑 |

## 3. 教师端课件转换边界

### 高保真还原

- 固定原 PPT 页数和顺序；
- 提取每页标题、正文和演讲者备注；
- 原 PPT 页面作为视觉画布；
- 在原页面上叠加讲解、聚焦、激光笔、动画和自动播放动作；
- 适合已有成熟课件、需要最大限度保持教师设计的场景。

### AI 增强

- 先审核和理解原始材料；
- 调用 `lib/learning-skills/` 中的教学设计能力；
- 增强目标、结构、解释、练习、互动与评价；
- 仍输出 OpenMAIC Scene/Action，而不是另一种课件格式；
- 适合内容重构和教学效果优化。

## 4. 关键数据链路

```text
PPTX/PDF
  → Importer / 文档解析
  → CoursewareMode（fidelity | ai-enhanced）
  → generationSession
  → SceneOutline[]
  → Scene + Action[]
  → Qwen3 TTS / 图片 / 视频资源
  → Asset Pool + IndexedDB
  → Source Trace + Scene Review + Release Gate
  → Classroom Playback Runtime
```

开发新功能时，应在这条链路中扩展明确的数据契约，避免新增无法被课堂运行时识别的旁路产物。

## 5. 本地运行与验证

项目目录：

```text
02-OpenMAIC验证/OpenMAIC
```

推荐使用项目外的统一启动脚本：

```powershell
..\start-openmaic.ps1
```

健康检查：

```text
GET http://localhost:3100/api/health
```

常用命令：

```powershell
pnpm dev
pnpm build
pnpm test
pnpm test:e2e
```

## 6. 文件放置规范

- 产品代码：放在 `app/`、`components/`、`lib/` 或 `packages/` 对应职责目录；
- 测试：与功能层级对应放入 `tests/` 或 `e2e/`；
- 可安装技能：放入 `skills/`；
- 教师端规格、计划、交接、验证记录和测试素材：统一放在项目外的 `07-教师端智能体/01-开发资料/`；
- 验证报告、演示 PPT、截图和课件成品：统一放在项目外的 `03-课件制作/`；
- 临时构建缓存：使用 `.codex-build/`、`.artifacts/`，不得提交；
- 不再创建 `.worktrees/teacher-agent-langgraph`、`app/teacher-agent/` 或 `lib/teacher-agent/` 平行实现。

## 7. 后续开发检查清单

1. 明确功能属于高保真路径、AI 增强路径还是共享课堂运行时；
2. 优先复用 Importer、Scene/Action、Asset Pool 和 Playback Runtime；
3. 确认生成阶段产生的 `audioId`、元素定位和动作时间线可持久化；
4. 同时验证“上传 → 模式选择 → 生成 → 审核 → 课堂播放”；
5. 保证 `localhost:3100` 是唯一对外开发入口；
6. 运行相应测试并记录真实 PPTX 的端到端结果。
