# 教学阶段与版本

更新：2026-11-16。代码依据：[教学接口](../../backend/teaching/service.py)、[三类型状态](../../backend/teaching/typed_state.py)、[旧版推进](../../backend/teaching/progression.py)。

外层 `phase` 控制课堂生命周期：`idle → video → discussion → done`。视频回看和课后对话是结束后的交互，不能把前端视图名称直接等同于后端 phase。

| 会话类型 | 教学推进 |
|---|---|
| 新建三类型知识点会话 | `recall → reinforce（有未掌握点）→ wrapup`；首轮每点最多 5 轮、补强最多 8 轮 |
| 保存的旧版会话 | 保留 `recall/reinforce/discuss/wrapup` 及该会话配置，历史默认 8/4 轮不能套用到 v4 |
| 动态教学会话 | 使用独立受限执行器与版本化策略；以可信配置和会话保存版本为准 |

三类型会话按原始要求累计学生证据，回答当前一问不等于整个知识点掌握；“好，然后呢”不算掌握。程序选择目标和动作并更新状态，模型负责语义评估与教学表达。轮数达到上限也不表示掌握，反馈需保留未掌握或未完成结果。

课堂结束后可继续课后学习，反馈更新并保留课堂原始反馈；具体实施、历史修复和失败样例见[教学文档](../knowledge-teaching/README.md)。
