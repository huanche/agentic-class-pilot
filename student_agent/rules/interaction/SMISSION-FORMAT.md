# SMISSION Format

`SMISSION.md` stores one student's personal mission inside the current lesson. It is student-specific even when `TMISSION.md` is shared.

路径：`runtime/SMISSION.md`

## Template

```md
# SMISSION: {student id or name} {current mission}

## 学生的目标
{why this matters to the student}

## 成功的样子
- {observable outcome for this student}

## 兴趣钩子
- {interest the dialogue can connect to lesson content}

## 现在最接近的下一步
- {smallest evidence-backed next step}

## 约束
- {time, attention, physical limitations, preferences}
```

## Rules

- Interest hooks must be usable by the dialogue skill as questions, not just personal trivia.
- The next step should come from learning evidence, not from the teacher's wish list.
- Update the file only when the student gives evidence, not because a session happened.
- 本文件在**课程结束时**才更新（由 `class-interaction` 在 `ending` 阶段写）。
