# 日志规范(logging-standards)

> 本文档是三个服务(平台、学生 Agent、教师 Agent)日志实现与使用的**唯一标准**。
> 第 2 期日志基建(M0–M3)的每一项实现都以本文档为验收依据。
> 正本位置:平台仓库 `docs/logging-standards.md`;其余服务不得各自另立标准。

## 1. 统一事件格式

所有服务输出**一行一条 JSON** 到 stdout。字段固定如下:

| 字段 | 类型 | 说明 |
|------|------|------|
| `ts` | ISO8601 | 事件时间(UTC) |
| `level` | `debug\|info\|warning\|error` | 见分级标准 |
| `service` | `platform\|student-agent\|teacher-agent` | 服务名 |
| `event` | 见 §2 | 事件类型 |
| `outcome` | `success\|failure\|cancelled` | 结果;控制台据此聚合,不从 status_code/level 推断 |
| `request_id` | string\|null | 一次 HTTP 请求的关联 ID |
| `operation_id` | string\|null | 一次跨请求异步业务操作的关联 ID |
| `user_id` | string\|null | 仅认证完成后已知时写入 |
| `course_id` | string\|null | 仅已知时写入 |
| `session_key` | string\|null | 课堂会话,仅已知时写入 |
| `method` / `path` / `route` / `status_code` | — | 仅 http.* 事件;见下方路径规则 |
| `target_service` | string\|null | 仅 `http.client.completed`:`teacher-agent\|student-agent\|llm-provider` |
| `duration_ms` | number | 耗时(请求完成/外部调用完成) |
| `error_type` | string\|null | 异常类名(如 `TimeoutError`) |
| `error_code` | string\|null | **本项目自定义的稳定枚举**(如 `llm_timeout`、`upstream_unavailable`),供控制台聚合;新增须先登记 |
| `exception` | object\|null | 仅 error 级别:`{"message": 脱敏后截断 500 字符, "stack": 可选, 脱敏后截断 4000 字符}` |
| `detail` | object | 事件特有的少量字段(如 `model`、`retry_count`、`job`) |

**路径规则**:
- `route`:模板化路由(如 `/api/v1/courses/{course_id}/members`),**指标聚合(P95/错误率)只按 route**,避免 path 高基数;
- `path`:实际路径,**不含 Query String**;仅用于排障定位;
- 查询参数与路径中的业务参数一律不写入日志。

规则:
- **未知字段不写 null 以外的占位**;确实不知道的字段直接省略(`user_id` 等关联字段)。
- 一个 JSON 对象独占一行,禁止多行/美化输出。

## 2. 固定事件类型(首批)

| event | 何时产生 | 关键字段 |
|-------|---------|---------|
| `http.request.completed` | 每个入站 HTTP 请求完成时 | method/path/route/status_code/duration_ms/outcome |
| `http.client.completed` | 每次出站服务调用完成时 | method/path/route/status_code/duration_ms/outcome/target_service |
| `llm.call.completed` | 每次 LLM 调用完成时(成功或失败) | detail.model/duration_ms/outcome/error_code/error_type/retry_count(见 §4) |
| `state.changed` | 关键状态变更:课程发布、知识任务入队/完成、进度同步、会话结束 | detail.job 或 detail.entity |

后续新增事件必须先在本文档登记再实现。

## 3. 分级标准

| 级别 | 用于 | 例子 |
|------|------|------|
| `debug` | 仅开发排查用,生产默认关闭 | 请求体摘要、内部状态快照 |
| `info` | 正常业务动作 | 请求完成、模型调用成功、任务入队 |
| `warning` | 可自动恢复的失败、降级 | 模型调用重试中、下游超时但已兜底、数据未同步但已排队 |
| `error` | 需要人看的失败 | 模型调用最终失败、下游不可用、未预期异常(附脱敏堆栈) |

**HTTP 状态码 → 级别映射**(目的:让"错误率"与"需要工程师处理的错误"一致):

| 情况 | 级别 |
|------|------|
| 2xx / 3xx | `info` |
| 401 / 403 / 404 / 422(用户错误,属正常流量) | `info`;其频率异常由指标层告警,不在日志级别体现 |
| 408 / 429 / 预期可恢复的下游失败 | `warning` |
| 5xx / 未处理异常 / 模型调用最终失败 | `error` |

## 4. 异常与重试的记录口径

- **exception 字段**:`exception.message` 必须脱敏(剔除 URL 参数、上游响应体、业务正文)并截断 500 字符;`exception.stack` 可选,error 级别才带,脱敏后截断 4000 字符。原始异常对象不得直接序列化。
- **retry_count 语义**:只记**本服务显式执行**的重试次数;SDK/客户端内部隐式重试不可观测时**省略该字段**,不为填字段改造既有重试策略。改造调用策略属另行决策,不在日志范围内。

## 5. 必打与禁打

必打:
- 每个入站 HTTP 请求完成(切面统一打,业务代码不写)
- 每次出站服务调用、每次 LLM 调用(切面/装饰器统一打)
- 异常(按 §4 口径)
- 状态变更(§2 `state.changed`)

禁打(违者为缺陷):
- 循环体、高频轮询路径
- 聊天正文、模型原始 Prompt/Response
- 密码、Token、Cookie、认证头、服务密钥
- 用户邮箱、手机号等个人信息(id 除外)
- 查询参数、含敏感信息的原始路径参数值(进 `route` 模板)

## 6. request_id / operation_id

- **request_id**:一次 HTTP 请求一个。入站时校验外部传入的 `X-Request-ID`:仅接受 `[A-Za-z0-9_-]{8,64}` 或合法 UUID,**非法/缺失即重新生成**;响应头回写服务端最终值;出站调用透传。
- **operation_id**:一次跨请求异步操作一个(课程生成/发布、知识任务、进度同步、重试)。在任务入队处生成,随任务数据传播,任务内所有日志(含 LLM 调用、落库)携带;HTTP 上下文内两者同时存在,异步任务内通常只有 operation_id。
- 实现机制:Python 用 `contextvar`(MDC 等价物),由中间件/认证依赖设置;业务代码只读不传。Next.js 侧用请求作用域 AsyncLocalStorage。

## 7. 认证与 user_id

请求完成日志由中间件产生时**不含 user_id**(中间件先于认证执行,这是有意为之,避免认证逻辑分叉)。`get_current_user` 认证成功后将 user_id 写入 contextvar;中间件最终输出时读取,拿不到即省略。

## 8. 输出量控制

- `LOG_LEVEL` 环境变量控制级别,生产 `info`、开发 `debug`。
- uvicorn/Next 默认访问日志**关闭**,只留本规范的 JSON 行。
- 第三方库噪音:`app`/`student_agent`/`teacher_agent` 之外 root level 设 `warning`。
- 聊天等高频接口不做逐条 debug 输出。

## 9. 异步日志

当前阶段**同步写**(量级小,保证完整优先)。触发条件(满足其一再评估切异步队列):
- 单机 QPS 持续 > 100,或日志写入在压测中出现在请求耗时 P95 的前 3 因子里。
Python 侧预案:`QueueHandler` + 后台线程。

## 10. 输出与轮转的责任边界

```text
应用:只写 stdout JSON Lines,不自行建日志文件、不加 FileHandler
运行环境/启动器:收集 stdout → local-dev/*.jsonl(现状已由 local_dev.py 落盘实现)
轮转脚本:按天/大小切割、7 天前压缩、30 天删除
控制台后端:只读收集后的文件(见 §11 的查询服务)
```

任何服务私自加 FileHandler 即违规范(会导致重复日志、格式漂移、轮转冲突)。

## 11. 收集架构的演进(LogSource)

控制台的日志查询永远走**后端日志查询服务**,不直接读文件。实现按阶段替换,接口不变:

1. **开发(当前)**:`local-dev/*.jsonl` 文件读取,硬限制——最大查询时间范围 24h、单次最多 500 条、必须分页;
2. **生产早期**:容器 stdout → 轻量采集器落盘,同一个查询服务适配;
3. **规模化**:Loki(不选 ELK,运维成本不成比例)。

## 12. 测试要求

- request_id 校验:合法透传、非法/缺失重新生成、响应头回写。
- 脱敏:构造含 token/正文/密码/URL 参数的异常,断言 `exception.message/stack` 输出不含。
- 事件 schema:每个事件类型的 JSON 至少含 §1 必填字段(快照测试)。
- **级别映射**:2xx/3xx 与 401/403/404/422 → info;408/429/可恢复失败 → warning;5xx/未处理异常 → error。
- route 模板化:同一路由的不同资源 id 产出相同 `route`;`path` 不含 Query String。
- 中间件 `duration_ms` 为非负整数。

**共享契约测试**:平台与学生 Agent 两个测试套件加载**同一组** JSON Schema 与脱敏测试向量文件(存放于平台 `tests/logging_vectors/`),任一侧实现漂移即两侧同时测试失败。

## 13. 共享实现

按优先级:

1. 仓库内共享极小 Python 包(需打通两侧构建链,当前不做);
2. **当前采用**:两份极小模块(Platform: `app/core/structured_logging.py`;student_agent: `backend/infrastructure/structured_logging.py`)+ §12 所述的**共享 Schema 与测试向量 + 契约测试**——漂移由测试兜底,不靠人工自觉;
3. 禁止"只复制代码、无契约测试"的裸复制。

教师 Agent(TS)以 `lib/logger.ts` 为基础扩展同构字段,契约向量同样适用(TS 测试读取同一组 JSON 向量)。

## 14. 开发运维中心运行日志

超级管理员可在「开发运维中心 → 运行日志」按服务、时间和请求 ID 查询近期事件。请求 ID 查询包含正常和异常事件。列表提供事件、路由模板、状态码、耗时和错误类型等元数据，原始消息与异常正文保留在服务端日志。

本地 Windows 启动器产生的 `.runtime/local-dev` 日志可以直接查询。生产环境可将日志导出到专用目录，并在平台服务环境中设置 `DEV_CONSOLE_LOG_DIR` 指向该目录。容器部署时以只读方式挂载导出目录。

大陆环境可在运行对应服务的主机上执行以下导出命令，适用于平台和学生的 systemd 日志以及教师容器日志。按需要用 `--service platform`、`--service student` 或 `--service teacher` 选择本机服务。定期执行即可更新近期快照。

```bash
python3 scripts/mainland/collect_diagnostic_logs.py /var/lib/agentic-diagnostics
```

导出目录需预先创建。导出进程需要读取所选服务日志并写入该目录。可用 setgid 目录让导出文件继承目录组，并授予平台服务账号该组的读取权限。平台服务本身只需读导出文件。各次导出原子替换对应服务的快照，每个来源最多读取最近 2,000 行。看板再限制扫描字节数和返回条数，长期留存由各服务的日志系统负责。
