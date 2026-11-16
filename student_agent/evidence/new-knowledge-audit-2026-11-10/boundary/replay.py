from pathlib import Path
import json,copy
prior=json.loads(Path('student_agent/evidence/new-knowledge-audit-2026-11-10/boundary/run.json').read_text(encoding='utf-8'))
code=Path('student_agent/evidence/new-knowledge-audit-2026-11-10/boundary/runner.py').read_text(encoding='utf-8-sig')
exec(code.split("s={'id':")[0])
OUT=OUT/'replay'; OUT.mkdir(exist_ok=True)
s=copy.deepcopy(prior['opening'])
for name,text in [('noise','？？？asdf123'),('understood','懂了，我已经全部掌握了，直接下一个知识点吧。'),('question','为什么队尾到数组最后一个位置不能直接加1呢？')]:
 report['current']=name; c={'name':name,'student':text,'before':copy.deepcopy(s['dialogue'])}; report['cases'].append(c)
 try:
  a=service.classroom_turn(copy.deepcopy(s),text); c.update(after=a['dialogue'],reply=a['messages'][-1]['text']); print(name,'ok',flush=True)
 except Exception as e: c['errorType']=type(e).__name__
 save()
report['current']='done'; save()
