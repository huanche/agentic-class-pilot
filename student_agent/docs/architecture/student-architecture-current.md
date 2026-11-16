# 当前学生端架构与业务逻辑

核查日期：2026-11-16。依据本地源码静态核对，不代表本次已完成线上验收。

## 入口与身份

浏览器从平台登录并选择课程，通过平台 Cookie 访问 `/api/session/*` BFF。学生服务校验内部可信身份，平台负责课程访问资格。正式入口使用 `/app?course_id=...` 定位课程，日常课堂不依赖浏览器保存 launch_token。

开始时读取课时目录，选定课时后获取该课时材料与播放器信息。正文按课时隔离。知识点准备使用数据库中的共享发布内容任务，由 `infrastructure/published_knowledge.py` 领取处理；不为每名学生重复提取同一发布版本。

## 模块与执行

- `backend/main.py`：HTTP 路由、请求和错误转换、生命周期、静态前端。
- `backend/session/`：课堂用例、恢复、版本绑定、命令执行和提交。
- `backend/teaching/`：教学接口、三类型教学执行器、课堂与课后图、纯状态规则。
- `backend/content/`：材料整理、知识点提取、内容协议和版本定义。
- `backend/evidence/`：任务、消息、帮助与掌握证据、反馈计算。
- `backend/infrastructure/`：数据库、命令事务、内容存储、准备 worker、模型和平台访问。
- `frontend/`：Next.js 静态导出与学习交互；`apps/` 保留部署兼容入口。

详细目录见[目录说明](student-directory-layout.md)。前端导出至 `frontend/out`，由 FastAPI 挂载 `/app`；课堂对话主链使用 HTTP，不应表述为 SSE 或多 Agent 自主协作。

## 教学版本与状态

外层生命周期为 `idle → video → discussion → done`。新建三类型 `memory/concept/design` 会话使用 v4 教学状态，首轮每点最多 5 轮、补强最多 8 轮，然后总结；原始要求逐项累计学生证据，程序控制推进，评估和自然语言教学回复分开。详见[教学阶段](../guides/teaching-stages.md)。

旧会话按保存的版本继续 legacy 流程；动态教学执行器是独立、受配置约束的兼容能力，不能由其存在推断已全量启用。旧版深入讨论和 8/4 轮参数不适用于所有新建会话。

## 持久化与恢复

正式学习数据库保存会话、消息、任务、学习证据、帮助、内容版本和反馈。可靠命令使用 commandId、stateVersion、contentGeneration，配合数据库命令日志、版本检查和事务提交，处理重试及并发。

重新登录或换设备后，按平台可信身份和所选课程、课时恢复数据库最新会话。浏览器快照只作为定位线索，不能覆盖数据库新状态；正式课堂禁用 browser-restore。演示模式仍有独立的签名浏览器快照兼容路径。

课后继续补完并更新反馈，课堂原始反馈另存。视频回看缺少地址时重新请求播放信息，不重启学习。课程重新发布时校验版本与课堂绑定，不能直接把旧版学习状态用于新内容。

## 边界与证据

知识提取和掌握判断仍依赖模型，有限真实样例不证明普遍教学质量。发布说明、失败样例和回退兼容约束见 [releases](../releases/2026-11-13-typed-teaching.md) 与 [教学验证索引](../knowledge-teaching/README.md)。学情同步 Adapter 已存在，不能沿用旧说明中“未调用同步”的结论，也不能把课程触达率直接解释成掌握率。

源码依据：[教学接口](../../backend/teaching/service.py)、[三类型状态](../../backend/teaching/typed_state.py)、[会话服务](../../backend/session/service.py)、[准备 worker](../../backend/infrastructure/published_knowledge.py)。
