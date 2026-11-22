# 教学阶段与版本

按 2026-11-22 本地源码整理。 [教学接口](../../backend/teaching/service.py) · [三类型状态](../../backend/teaching/typed_state.py) · [旧版推进](../../backend/teaching/progression.py)

外层 `phase` 控制课堂生命周期：`idle → video → discussion → done`。视频回看和课后对话是结束后的交互，不能把前端视图名称直接等同于后端 phase。

| 会话类型 | 教学推进 |
|---|---|
| 新建三类型知识点会话 | `recall → reinforce（有待巩固点）→ wrapup`，首轮每点最多 5 轮，补强最多 8 轮。启用 `cards_version=1` |
| 保存的旧版会话 | 保留 `recall/reinforce/discuss/wrapup` 及该会话配置，历史默认 8/4 轮不能套用到 v4 |
| 动态教学会话 | 使用独立受限执行器与版本化策略；以可信配置和会话保存版本为准 |

三类型会话按原始要求累计学生证据，回答当前一问不等于整个知识点掌握；“好，然后呢”不算掌握。程序选择目标和动作并更新状态，模型负责语义评估与教学表达。轮数达到上限也不表示掌握，反馈需保留未掌握或未完成结果。

## 现行教学分支与提示词

| 环节 | 行为与源码 |
|---|---|
| 记忆类题组卡 | 模型生成 1–4 道单选或判断题，程序校验关联要求、打乱选项并判分。可分次提交，整组完成才计入一轮。未答部分可续做，聊天中的答案需回到卡片提交。在卡片旁请求讲解后，答对也不能单独证明独立掌握。 [出题提示词、校验和判分](../../backend/teaching/question_cards.py) · [题卡状态和答疑提示词](../../backend/teaching/card_teaching.py) |
| 概念类 | 根据实际回答和帮助记录选择提示或直接讲解。当同一待确认范围已给过启发，学生再尝试或仍有困难时可直接讲解。讲解本身不计入学生证据。 [概念策略](../../backend/teaching/concept_guidance.py) |
| 设计类 | 围绕原始能力、约束和成功标准组织构造任务，保留学生已提交的证据和待确认要求。 [三类型回复策略](../../backend/teaching/typed_teaching.py) |
| 对话评估和回复 | 现行自然回复路径先用 `submit_current_assessment` 评估学生原文，程序更新要求与教学计划，再生成面向学生的自然中文。首问跳过评估，题组卡使用独立出题、判分和答疑路径。 [评估与回复提示词、动态上下文](../../backend/teaching/typed_teaching.py) · [计划与推进](../../backend/teaching/typed_state.py) |
| 兼容流程 | 旧版课堂和课后使用各自的图与提示词。动态教学由显式配置选择，并保留自己的决策和回复协议。 [旧版提示词](../../backend/teaching/prompts.py) · [动态流程](../../backend/teaching/dynamic_teaching.py) |

三类型会话结束后可补完未掌握点。课后使用独立的补完状态，课堂 5/8 轮上限仅用于课堂。课后反馈可更新，课堂原始反馈保留。历史实施和失败样例见[教学文档](../knowledge-teaching/README.md)。
