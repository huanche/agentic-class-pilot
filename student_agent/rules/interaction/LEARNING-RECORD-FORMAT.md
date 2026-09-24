# LEARNING-RECORD Format

Learning records 使用顺序编号：`0001-slug.md`、`0002-slug.md`，依次递增。

一条学习记录记录**关于这个学生的、有证据支撑的、持久的知识**：一个被纠正的误解、一个被展示出来的技能、或新披露的已有知识。

路径：`runtime/LEARNING-RECORD.md`（当前课）或 `runtime/learning-records/`（历史累积）

## Template

```md
# {学到了什么，简短标题}

{1-3 句话：关于这个学生，我们知道了什么新东西，以及它为什么影响下一次课。}

## Evidence
{学生说了什么或做了什么，支撑这个判断}

## Implications
{这解锁了什么，或排除了什么}
```

## Rules

- **只在有证据时写**。一节课覆盖了材料，不等于学会了。
- 后一条记录与前面矛盾时，把前面那条标为 `Status: superseded by LR-NNNN`，**不要删除**。
- 保持简短。它用于指导未来的课，不是课堂日志。
- 本文件在**课程结束时**更新（由 `class-interaction` 在 `ending` 阶段写）。
