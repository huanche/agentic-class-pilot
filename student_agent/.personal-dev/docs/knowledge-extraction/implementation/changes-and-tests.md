# 三类型课时知识点提取实施记录

日期：2026-11-05。工作树：`typed-knowledge-extraction`，分支：`lzm2`。依据 [当前方案](../design/plan.md) 实施，未部署。

## 已实现的行为

- 统一协议定义在 `backend/content/knowledge_schema.py`，仅接受 `memory`、`concept`、`design`。
- 工具参数为 `points`；每个点仅有 `title`、`type`、`details`。课程、课时、版本及正式 ID 由程序处理。
- memory 的 details：`statement`、`requiredElements`。
- concept 的 details：`explanation`、`understandingPoints`。
- design 的 details：`capability`、`constraints`、`successCriteria`。constraints 可为空，其余要点数组必须非空。
- 禁止额外字段、非法类型、空白必填文本和错误类型分支。暂设每批最多 120 项、每个要点数组最多 40 项、每段文本最多 6000 字符。
- 名称和内容允许改写；没有独立 formulas 字段，不要求引用或来源位置，不增加在线语义审查。

## 反馈修正闭环

`learning_points` 每次创建一个 `create_agent`，通过 `ToolStrategy(submit_knowledge_points)` 绑定 Pydantic 协议。结构错误由框架生成 ToolMessage，模型在同一消息上下文中继续提交完整批次。没有有效工具提交、工具名错误或参数 JSON 损坏也会获得反馈。

中间件统一限制首次生成加两轮修正，共最多 3 次模型调用；总预算 90 秒，单次请求最多 45 秒且不超过剩余预算。提取模型的 SDK 自动重试关闭。通过后直接结束，不再调用模型生成“完成”文本。不支持工具调用的接口会明确失败，不退回普通文本解析。

空输入不调用模型；工具明确提交空 points 时返回无内容状态；超时或请求错误不冒充无内容。超限失败不发布其中部分合格项。失败任务记录尝试次数、错误和最后一次草稿。已分类的提取失败标记为需显式重试，后台 worker 不自动重启另一个三次循环；现有重试入口可以重新发起一次任务。

程序在结构通过后合并完全重复项：比较 type、title、details，仅去首尾空白及统一换行；保留内部代码字符、数组顺序和第一次出现的位置。不同类型、同名不同内容或仅语义接近的项不会合并。

## 保存与兼容

- 新内容使用 schemaVersion=2，保留 type/details；content/description 由结构派生，供旧教学入口读取，不标为原文引用。
- 整批结果顶层保留程序绑定的 courseId、lessonId 和 sourceRevision。
- 正式提取的知识点 ID 使用程序传入的课程、课时作用域，避免相同内容在不同课时共用学情标识。
- 提取器标识包括协议和提取版本；原教学 CURRICULUM_VERSION 不随本次提取升级而改变。
- 旧 schemaVersion=1 的保存、校验和会话固定机制继续保留，不自动推断为 concept。
- V2 topics 携带 type/details，下游包括已有动态试点可读取；空来源不会阻断新内容。旧 V1 动态试点的引用约束保留。
- 本次不改造完整的按类型教学策略、阶段或学生 UI。
- 任务尝试的失败诊断与旧内容快照分开处理，避免重试失败修改不可变历史内容的指纹。

## 验证范围

测试使用真实 create_agent/ToolStrategy 执行图，模型由可控的 BaseChatModel 或真实 ChatOpenAI + httpx MockTransport 替代；后者验证实际请求序列化、工具消息反馈和再次提交，不访问外部模型服务。

数据库回归使用本工作树下独立初始化的回环 PostgreSQL。测试自动创建、删除随机测试库，结束后停止集群，不读取正式或开发数据库配置。

验证结果：

| 检查 | 结果 |
| --- | --- |
| 后端完整回归（含独立 PostgreSQL） | 229 通过，2 跳过 |
| 最终提取、内容及历史版本定向回归 | 47 通过 |
| 前端单元测试 | 42 通过 |
| Python 编译、依赖一致性、Git 差异检查 | 通过 |

两项跳过用例分别为平台解耦 analytics/knowledge 数据库测试，需要额外配置 `DECOUPLING_TEST_DATABASE_URL`；本次独立学生库未替代该配置。完整回归之后补充了端到端用例与失败任务预算保障，并再次完成上述 47 项定向回归。

后端命令：`.venv/Scripts/python.exe -m pytest student_agent/backend/tests -q -rs`；数据库测试需按 tests/conftest.py 配置独立回环 `STUDENT_TEST_DATABASE_URL`。该测试环境另安装了平台迁移回归所需的 Alembic 和 SQLModel，未将其加入学生运行时依赖。

前端命令：`node --test student_agent/frontend/tests/unit/*.test.mjs`。测试结束后随机测试库数量为 0，独立 PostgreSQL 集群已停止。

## 后续真实课时试验（2026-11-05）

已使用当前配置的 deepseek-v4-flash，在真实课时“数据结构 / 第1周 / 第1次课”的 13 个播放场景上完成自然提取：首轮通过，11 项（memory 2、concept 7、design 2），耗时 10.845 秒。另起独立故障注入轮，删除首轮响应中 concept 的 understandingPoints；真实模型收到结构错误后第二轮通过，共 13 项，耗时 22.363 秒。

真实接口首先暴露 thinking 模式不支持 ToolStrategy 强制工具选择的问题；已在 extraction_model 中仅对官方 DeepSeek 提取请求关闭 thinking，普通教学及其他供应商保持原配置。模型名、地址和密钥未更换，Agent 反馈修正流程保留。相关回归 42 通过、5 个数据库用例跳过，本轮不写数据库。

详见 [实测报告与原始结果](../validation/2026-11-05-live-model/README.md)。该次试验只读读取本地真实课件，结果保存为工作树文件，未部署或写入正式知识包。尚未进行教师人工评分或多课时准确率评测；结构通过不代表教学内容百分之百正确，两次独立提取的拆分及分类也有差异。
