from pathlib import Path
import json
p=Path('student_agent/evidence/new-knowledge-audit-2026-11-10/boundary'); x=json.loads((p/'continuation/run.json').read_text(encoding='utf-8')); a=x['cases']; last=a[-1]['after']['points'][0]
assert a[-1]['after']['stage']=='wrapup'
assert (last['recall_attempts'],last['reinforce_attempts'])==(5,8)
assert len({c['reply'] for c in a[:4]})==1
with (p/'report.md').open('a',encoding='utf-8') as f:
 f.write('''

## 增量：完整5+8与课后续学

在原8轮真实状态后恢复内存session，独立保存 continuation/run.json；没有数据库持久化或HTTP恢复验证。执行 continue.py 增加5次学生回答，另finish（无模型）、真实课后开场及1次课后回答，共13次额外模型请求。**本组最终共61次真实模型请求**；原20次学生输入＋3次重跑＋5次限额续测＋1次课后回答=29次学生输入，另原开场和课后开场各1次。

- **高优先级教学质量问题：第9/10/11/12轮回复逐字相同。** 已做字符串相等断言。均说“你已经知道rear撞墙、前面还有空位”，但学生全程只说不知道，没有证明这些认识。首要求仍needs_help，程序没有虚假确认；这是自然语言虚构学生已知和反复追问。4轮都以相同rear7绕回0计算题结束。
- 第13答真实完成wrapup，程序recall_attempts=5、reinforce_attempts=8。总结没有再出题，没有宣称全部掌握；具体将后续空满等称为“还没确认”，保留了未确认和缺口区别。
- finish后真实课后开场重新给出最初front3 rear8的问题；一次“还是不知道”后转讲取模并问rear5。说明service内存轨迹可以续学；不等于验证数据库保存恢复。课后是否过度重头考需要进一步评估，不能把旧题再现本身当成错误。

增量断言命令检查wrapup、5/8计数和四轮回复完全相同，均通过。没有测试学生提前退出再恢复，该覆盖仍空缺。
''')
print(last['recall_attempts'],last['reinforce_attempts'],'four identical replies confirmed',len(x['trace']))
