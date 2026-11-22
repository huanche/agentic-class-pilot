# 当前学生端架构与业务逻辑

按 2026-11-22 工作区源码（`e9929e5`）核对。线上部署版本以发布记录为准。

## 入口与身份

浏览器从平台登录并选择课程，通过平台 Cookie 访问 `/api/session/*` BFF。正式入口使用 `/app?course_id=...` 定位课程。平台向学生服务转发可信身份，校验课程访问资格，正式课堂的写请求使用 CSRF 校验。 [平台入口](../../../platform/backend/app/api/routes/student_bridge.py) · [Cookie BFF](../../../platform/backend/app/api/routes/student_learning.py)

开始时读取课时目录，选定课时后获取该课时的发布材料与播放器信息。学生前端通过 iframe 复用播放器，使用 `postMessage` 接收播放事件。知识点按课时视频版本共享准备任务，处理过程见[提取与内容版本](../knowledge-extraction/README.md)。 [播放器适配](../../frontend/src/integration/platform-player-adapter.js)

## 模块与执行

- `backend/main.py`：HTTP 路由、请求和错误转换、生命周期、静态前端。
- `backend/session/`：课堂用例、恢复、不可变内容绑定、命令执行和提交。
- `backend/teaching/`：教学接口、三类型教学执行器、课堂与课后图、纯状态规则。
- `backend/content/`：材料整理、知识点提取、内容包构建和版本定义。 `preparation.py` 负责把提取结果编译为内容包，任务与写库由基础设施管理。
- `backend/evidence/`：任务、消息、帮助与掌握证据、反馈计算。
- `backend/infrastructure/`：数据库、命令事务、内容存储、准备 worker、模型和平台访问。
- `frontend/`：Next.js 静态导出与学习交互；`apps/` 保留部署兼容入口。

前端导出至 `frontend/out`，由 FastAPI 挂载 `/app`。课堂操作使用 HTTP 命令和状态读取，准备阶段及命令恢复使用轮询。 [目录说明](student-directory-layout.md) · [前端会话接口](../../frontend/src/integration/learning-session.mjs)

## 教学版本与状态

外层生命周期为 `idle → video → discussion → done`。新建三类型 `memory/concept/design` 会话使用 v4 教学状态和 `cards_version=1`，课堂首轮每点最多 5 轮，补强最多 8 轮。记忆类题卡由程序判分，概念类和设计类对话使用模型评估和自然语言回复，程序根据学生证据汇总原始要求并推进。知识点目录定位已有消息，前后知识点按钮执行会话命令。 [教学阶段](../guides/teaching-stages.md)

旧会话按保存的版本继续 legacy 流程；动态教学执行器是独立、受配置约束的兼容能力，不能由其存在推断已全量启用。旧版深入讨论和 8/4 轮参数不适用于所有新建会话。

## 持久化与恢复

正式学习数据库保存会话、消息、任务、学习证据、帮助、内容版本和反馈。可靠命令使用 commandId、stateVersion、contentGeneration，配合数据库命令日志、版本检查和事务提交，处理重试及并发。

重新登录或换设备后，按平台可信身份和所选课程、课时恢复数据库最新会话。浏览器快照只作为定位线索，不能覆盖数据库新状态；正式课堂禁用 browser-restore。演示模式仍有独立的签名浏览器快照兼容路径。

课后继续补完并更新反馈，课堂原始反馈另存。视频回看经播放接口补齐播放信息。刷新课时上下文时校验视频版本，同版本更新目录信息，视频版本变化时重新初始化课堂并递增 `contentGeneration`。提取器变化可为同一视频生成新的内容包，已绑定会话继续按自己的 `contentRef` 读取。 [会话刷新与回看](../../backend/session/service.py) · [内容绑定](../../backend/session/content_binding.py)

## 边界与证据

平台可通过学生服务的内部接口读取名册进度、学习数据和对话记录。名册掌握数取当前已发布视频版本中与准备清单匹配的真实评估。页面通过平台 `/api/session/presence` 报告活动，学生服务按学员、课程和课时版本核对会话归属。 [学生内部接口](../../backend/internal_platform.py) · [平台活动上报](../../../platform/backend/app/api/routes/student_learning.py)

知识提取与语义评估依赖模型。抽样对话、失败样例和回退兼容记录按各自版本阅读。 [发布说明](../releases/2026-11-13-typed-teaching.md) · [教学验证索引](../knowledge-teaching/README.md)

源码依据：[教学接口](../../backend/teaching/service.py)、[三类型状态](../../backend/teaching/typed_state.py)、[会话服务](../../backend/session/service.py)、[准备 worker](../../backend/infrastructure/published_knowledge.py)。
