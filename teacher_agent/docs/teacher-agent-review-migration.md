# Teacher Agent 工作区迁移说明

## 范围

吸收本地 OpenMAIC 的教师聊天模型设置、网页检索和课时内容审核衔接。
不替换平台鉴权、课程 ID 桥接、个人模型配置、数据库、对象存储或知识图谱实现；不涉及首页品牌和 PPT 来源选择。

## 课时内容审核

- `create-lesson-files` 始终生成需要确认的计划。
- 需要正文内容的计划进入既有 `/course-space/{courseId}/prepare` 页面，单课时与多课时统一处理。
- 页面逐课时生成草稿；此时不保存、不覆盖原文件。全部生成成功、教师审核后才统一保存。
- 某课时生成失败时，展示错误并禁止保存；可只重试失败课时，保留其他课时已编辑的草稿。
- 取消、关闭页面或返回工作台不会写入草稿。尚未保存的草稿正文只保存在页面内存中；刷新后须重新生成。
- 支持课时目标、知识点、教学活动、课件页面、讲稿片段、习题和评价指标全部七类文件。
- 操作执行 API 拒绝 `populateContent` 直接写入，即使旧客户端提交无需确认的计划也不能绕过此流程。
- 创建空结构文件仍通过确认后的操作执行 API 完成，已有同类型文件保持不变。

### 草稿 API

`POST /api/course-space/{courseId}/lesson-files/draft`

请求包含 `lessonId`、`fileTypes` 和可选 `instruction`。响应包含 `lessonId`、`lessonTitle`、`drafts` 和 `baseVersion`，没有持久化副作用。

`PATCH /api/course-space/{courseId}/lesson-files/draft`

批量请求包含 `lessons` 数组，每项为 `lessonId`、审核后的 `drafts` 和 POST 返回的 `baseVersion`。
保留单课时顶层请求形状，但同样必须携带 `baseVersion`；旧草稿客户端需要随审核页面一起升级。

保存前在现有 `updateServerCourse` 更新回调中验证全部目标和文件版本；任何课时已删除或选中文件发生变化，返回 409，不提交本次批次。
验证通过后使用一次课程更新保存，保留已有文件 ID、创建时间及发布等元数据，不修改未选择的文件。
版本指纹是乐观并发检查，不是授权凭证；权限仍由既有平台中间件管理。此检查沿用存储层现有锁语义，不新增跨进程数据库事务保证。

## 网页检索与模型链路

- 教师聊天提供模型设置、网页检索开关和设置入口，保留知识图谱按钮。
- 开启检索时，前端先请求既有 `/api/web-search`，成功后将来源上下文传入课程 Agent API；检索失败会显示错误，不静默假装已检索。
- 网页上下文最多 24,000 字符，提示词要求区分课程材料与网页来源、保留链接，并将网页文本视为参考资料而非操作指令。
- 聊天请求传递模型、提供商、服务地址及推理配置；这些配置不存入会话事件。
- API 从可信平台查询获得个人 BYOK 配置，不接受请求体伪造的 `platformOverrides`。
- 兼容模型调用优先级保持：平台个人 BYOK → 服务端阶段路由 → 客户端模型选择 → 默认模型。
- Harness 使用独立模型配置；聊天设置不改变 Harness 模型。网页上下文进入两种模式的提示词。
- Harness 未配置或失败时按原行为降级至兼容调用；截图请求直接使用兼容调用。
- 课时草稿生成沿用原生成阶段的服务端模型配置；聊天的模型选择和网页上下文并未扩展到产物生成接口。

## 验证

- Vitest：教师规划、前端检索请求链、课程 Agent API、草稿生成/批量保存、直接执行防绕过、Harness 和兼容分支。
- 现有课程空间、平台鉴权和提供商配置测试一并回归；未配置真实数据库时，迁移测试内的数据库操作不执行。
- Chromium：单课时确认与正文编辑、多课时统一保存、失败重试保留编辑、取消不写入、并发冲突展示。
- 独立浏览器配置：[playwright.teacher-review.config.ts](../playwright.teacher-review.config.ts)，使用 3217 专用端口及 mock API。
- 设置 `NO_PROXY=localhost,127.0.0.1` 后运行 `pnpm exec playwright test --config=playwright.teacher-review.config.ts`，避免环境代理错误判断本地服务已启动。
- 使用 `pnpm exec tsc --noEmit --incremental false` 检查类型。首次安装须完成项目 `postinstall` 的内部包构建。
- 自动化测试不调用真实 LLM、Harness、网页检索服务或对象存储；上线前仍需使用实际服务配置进行联调。