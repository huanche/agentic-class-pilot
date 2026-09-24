# Platform Integration Porting Guide（平台适配移植指南）

本文件登记本仓库（教师 Agent）为对接平台基座所做的**全部**修改，并约定修改的组织方式，
使得上游教师 Agent 代码更新时可以低成本迁移。维护规则：

1. **平台语义只存在于独立模块**：`lib/server/platform-auth.ts`（身份/中间件）与
   `lib/server/platform-course-bridge.ts`（课程身份/登记/id 生成）。业务文件不得内联
   `PLATFORM_*` 判断。
2. **业务文件只保留最小挂钩（hook）**：每个挂钩是一行到几行的调用，逐条登记在下面。
3. 新增适配一律先加模块、再挂最小钩；修改本文档与
   `platform/docs/integration-log.md`。
4. 学生 Agent（`agent/student_agent/SZU_Student_Agent`）后续适配遵循同一约定
   （独立 `platform` 适配模块 + 最小挂钩清单）。

## 独立模块（上游更新时整文件平移，无冲突）

| 文件 | 职责 |
|---|---|
| `lib/server/platform-auth.ts` | 每请求平台鉴权（authorize 回调、cookie 转发、伪造头剥离、服务密钥委托、`x-platform-delegated` 标记、fail-closed） |
| `lib/server/platform-course-bridge.ts` | 教师身份解析（`resolveTeacherId`）、委托判定、courseId 校验/生成（平台 UUID / 独立 nanoid）、平台登记（幂等+有界重试） |
| `lib/integration/platform-links.ts` | 平台导航适配：从 `NEXT_PUBLIC_SAAS_HOST_ORIGIN` 读取平台地址（工作台/学生管理/学习数据 URL），供总览页"返回管理平台"；生产为构建期内联，改环境变量需重新构建 |
| `lib/integration/player-host-events.ts` | 嵌入式播放器事件适配：向同域平台宿主页发送场景完成与整课播放完成事件 |
| `tests/server/platform-auth.test.ts` | 上述身份模块的 9 项单测 |
| `scripts/dev-3200.ps1` / `scripts/dev-3200-platform.ps1` | 独立/平台鉴权两种启动器（数据目录隔离；`--hostname ::` 双栈监听） |
| `scripts/acceptance/verify_teacher_3200.py` / `verify_phase2_identity.py` | 阶段 1/2 验收脚本 |

## 业务文件挂钩清单（上游更新后需重放的小改动）

| 文件 | 挂钩 | 说明 |
|---|---|---|
| `middleware.ts` | 顶部 import + `PLATFORM_AUTH_ENABLED` 分支（5 行） | 平台模式全量委托 `platformMiddleware` |
| `app/api/course-space/route.ts` | GET/POST 用 `resolveTeacherId` 取身份；POST 加 `platformProvidedCourseId` 幂等路径 + `registerCourseWithPlatform`（委托调用跳过） | 文件结构与上游保持同名同序，平台语义全部来自 bridge |
| `lib/server/course-space-storage.ts` | `createServerCourse` 一行：`id: generateCourseId(input.id)` + import | 平台/独立两种 id 策略 |
| `lib/course-space/types.ts` | `CreateCourseSpaceInput.id?: string` 一行 | 平台传入 UUID |
| `lib/server/api-response.ts` | `API_ERROR_CODES` 增加一项 `SERVICE_UNAVAILABLE` | 登记失败语义 |
| `lib/server/classroom-storage.ts` | `CLASSROOMS_DATA_DIR` / `CLASSROOM_JOBS_DATA_DIR` 环境变量化（镜像 `COURSE_SPACES_DATA_DIR` 既有模式） | 数据目录隔离 |
| `app/api/classes/route.ts` | 通过 `resolveTeacherId` 使用中间件注入的可信教师身份 | 授课列表按当前教师隔离；独立模式才回退 `local-teacher` |
| `lib/integration/platform-links.ts` | `platformHomeUrl()` 指向平台 `/teacher` | 课程中心和授课总览返回统一教师产品门户 |
| `components/course-space/course-center.tsx` | 返回按钮改调 `platformHomeUrl()`（import + 一处 onClick） | 课程中心总览返回平台 8080 |
| `app/classes/page.tsx` | 返回按钮改调 `platformHomeUrl()`（import + 一处 onClick） | Class 总览返回平台 8080；课程内部页面导航保持教师端内部路由 |

## 与平台适配无关的修改（上游合并时按普通提交处理）

| 文件 | 性质 |
|---|---|
| `lib/server/course-space-storage.ts` 的 `updateCourseJobIfPresent` + `app/api/course-space/[courseId]/artifacts/[artifactId]/route.ts` 两处调用替换 | 修复挂载产物激活 500 的存量 bug；纯增量函数 |
| `tests/course-space/artifact-activation.test.ts` | 上述 bug 的回归测试 |
| `tests/course-space/migration.test.ts` | 上游类型漂移的夹具修复 |
| `.gitignore`（node_modules 覆盖子包） | 工程卫生 |

## 环境变量契约

| 变量 | 作用 | 设置处 |
|---|---|---|
| `PLATFORM_AUTH_ENABLED=true` | 启用平台身份模式（middleware 分支 + UUID id + 登记） | dev-3200-platform.ps1 |
| `PLATFORM_AUTH_URL` | 平台基址（authorize/courses 前缀 `/api/v1`） | 同上 |
| `PLATFORM_PUBLIC_URL` | 未登录页面重定向目标 | 同上 |
| `PLATFORM_SERVICE_KEY` | 服务间密钥（= 平台 `TEACHER_SERVICE_KEY`） | 同上（运行时从 platform/.env 读） |
| `COURSE_SPACES_DATA_DIR` / `CLASSROOMS_DATA_DIR` / `CLASSROOM_JOBS_DATA_DIR` | 数据目录隔离 | 两个启动器 |

## 上游更新时的迁移步骤

1. 合并上游版本；冲突只可能出现在"挂钩清单"里的 6 个文件。
2. 独立模块整文件平移（上游不存在这些路径，无冲突）。
3. 按挂钩清单逐条重放（每条都是局部小改）。
4. 验证：`pnpm exec tsc --noEmit`；`pnpm exec vitest run tests/server tests/course-space`；
   起服务后跑 `scripts/acceptance/verify_teacher_3200.py`（独立态）与
   `verify_phase2_identity.py`（平台态）。
5. 更新本文件的挂钩清单（若新增/变更）。

## 模型配置入口（平台扩展）

| 文件 | 职责 |
|---|---|
| `app/settings/page.tsx` | 独立模型配置入口；复用上游 `SettingsDialog`，关闭弹窗后保留可重新打开的页面，并提供返回平台按钮。该文件为独立新增模块，上游更新时整文件平移。 |

## Published classroom narration repair

| File | Porting responsibility |
|---|---|
| `app/api/course-space/[courseId]/classrooms/[classroomId]/narration/route.ts` | Independent platform endpoint. Regenerates persisted narration only after the existing course-scoped middleware authorizes the teacher. Copy the complete file on an upstream refresh. |
| `lib/server/course-space-database.ts` | Small hook: retain `readClassroomBindingFromDatabase` so the endpoint verifies the classroom belongs to the course in its URL. |
| `lib/server/classroom-media-generation.ts` | Small hook: retain the generation summary, clear `audioInvalidated` only after successful synthesis, and keep failed speech actions unchanged. |

Acceptance: `pnpm exec tsc --noEmit`; POST the narration endpoint as the owning teacher; then read the classroom as an enrolled student and verify every speech `audioUrl` returns `200 audio/*` through the unified gateway.