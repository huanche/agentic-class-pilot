## 2026-11-04 三类型提取发现
- 当前 lzm2=0b30b39；knowledge.py 仍为普通文本 JSON 与原文校验，lesson_content 白名单会丢弃新字段。
- 当前要求没有在线来源扩展；v2 内容需要结构校验并保留 type/details，不能要求原文引用。
- 原共享虚拟环境已有 langchain-openai/langgraph/pydantic/pytest，但缺少 langchain；为独立工作树建立测试环境，不修改共享环境。

### 三类型实现核对
- LangChain ToolStrategy 在 model 节点内执行参数校验并附加 ToolMessage；中间件需选择 AIMessage，不可假定最后一条是模型消息。
- create_agent 的 ToolStrategy 足以承载本期唯一硬门槛（结构）；成功结构返回后立即结束，去重由程序执行，无须再让模型回一次完成文本。
- 已有动态试点把空 sourceRefs 的主题过滤掉；为 V2 添加最小兼容，只接受已验证的 type/details，允许来源为空，V1 保持既有要求。

### 当前模型真实兼容性
- DeepSeek官方API本轮实际返回400，原因是默认thinking与ToolStrategy强制tool_choice不兼容；已仅在提取适配器为官方host关闭thinking并添加供应商边界回归。
- 模型输出可符合三类型协议且真实反馈能修复字段缺失；独立两轮的11/13项和memory/concept分类变化说明结构稳定不保证教学粒度稳定。
