## 2026-11-04 三类型提取实施
已确认新工作树 lzm2，仅方案文档未提交；开始协议、Agent 循环和内容兼容实施。

### 2026-11-05 续作进度
- 三类型 Pydantic 模型与真实 create_agent/ToolStrategy 循环已实现；21 项提取测试通过，覆盖结构反馈、工具调用损坏、普通文本、三次上限和总超时。
- V2 内容保存 type/details，派生兼容正文；提取器版本与既有教学版本分开，旧会话不升级。
- 单元回归初次发现新纯协议模块未加入架构白名单，已补齐；Agent 中间件最初误把 ToolStrategy 追加的 ToolMessage 当成模型消息，已修复并通过真实循环验证。
- 新虚拟环境独立安装依赖。隔离 PostgreSQL 初次使用含中文路径的二进制失败；复制到本工作树 ASCII 路径后初始化成功。
- 前端 42 项单元测试通过；后端含隔离 PostgreSQL 的完整回归进行中。

### 数据库回归修正（2026-11-05）
- 初次完整回归：222 通过、2 失败、2 跳过。失败诊断覆盖旧 coverage 导致历史版本指纹改变，已改为合并任务诊断、归档时剥离尝试元数据。
- 次轮：226 通过、1 失败、2 跳过，剩余为独立环境缺少 sqlmodel；已安装平台迁移测试需要的 Alembic/SQLModel，不增加学生运行时无关依赖。
- 实际发布与回退入口均传入程序绑定的 courseId/lessonId，正式知识点 ID 带课时作用域，避免跨课时学情覆盖。

### 2026-11-05 三类型提取交付
- 后端完整回归 229 passed / 2 skipped（平台解耦专用测试库未配置）；最终提取、保存与版本回归 47 passed，覆盖真实 Agent→修正→PostgreSQL→学生恢复。
- 前端单元测试 42 passed；compileall、pip check、git diff --check 通过。
- 增加已分类提取失败的显式重试标记，防止后台 worker 自动重新开启另一个三次循环；验证显式重试可恢复。
- 测试随机数据库剩余 0，独立集群已停止。实现说明：docs/knowledge-extraction/implementation/changes-and-tests.md。
- 仅本工作树 lzm2 代码与文档有改动；未提交、未推送、未部署，未使用真实模型验证教学准确率。

### 2026-11-05 真实课时验收
- 只读从本地已发布快照读取数据结构第1周第1次课（13场景，6024字符），使用现有 DeepSeek v4 flash 配置。
- 首次真实请求400：thinking模式不支持ToolStrategy强制工具选择。仅官方DeepSeek提取请求关闭thinking，普通教学调用保持原样，模型/密钥/地址未更换。
- 自然提取1次成功：11项（memory2/concept7/design2），10.845秒。
- 独立注入轮删去首个concept的understandingPoints；模型收到具体结构反馈后第二次提交成功，13项（4/7/2），22.363秒。注入前原始提交也通过同一协议，故障明确来自测试器。
- 两轮独立粒度有差异，未人工修改输出或宣称准确率；未部署、未写正式知识包、未修改学生记录。
- 相关回归42 passed/5 skipped（数据库用例本轮不运行）；敏感配置检查、实际输出协议校验通过。
- 报告与JSON：docs/knowledge-extraction/validation/2026-11-05-live-model/；本机脚本与快照在忽略目录.runtime/typed-knowledge-live。

### 2026-11-05 文档归类
- 本次交付统一收拢到 docs/knowledge-extraction/，按 design、research、implementation、validation、records 分类，新增 README 总入口。
- 方案、实施记录及实测产物移动后同步更新链接；历史调研复制为背景资料，本次追加的根目录计划与日志迁入 records，原有历史内容保留。
- 本地 Markdown 链接全部有效，4 份实测 JSON 可解析；移动时校验文件哈希一致。本次不修改业务代码，不重跑模型。
