from pathlib import Path
import json,copy
prior=json.loads(Path('student_agent/evidence/new-knowledge-audit-2026-11-10/boundary/run.json').read_text(encoding='utf-8'))
code=Path('student_agent/evidence/new-knowledge-audit-2026-11-10/boundary/runner.py').read_text(encoding='utf-8-sig')
exec(code.split("s={'id':")[0])
OUT=OUT/'continuation'; OUT.mkdir(exist_ok=True)
s=copy.deepcopy(prior['opening'])
for c in prior['cases']:
 if c['name'].startswith('repeated_unknown_'):
  s['messages'] += [{'role':'student','text':c['student'],'phase':c['before']['stage']},{'role':'assistant','text':c['reply'],'phase':c['after']['stage']}]
  s['dialogue']=copy.deepcopy(c['after'])
report['restoredFrom']='run.json repeated_unknown_8 in-memory snapshot, no database'
for i in range(9,14):
 report['current']='repeated_unknown_'+str(i); c={'name':report['current'],'student':'还是不知道，我不知道怎么回答。','before':copy.deepcopy(s['dialogue'])}; report['cases'].append(c)
 try:
  s.update(service.classroom_turn(s,c['student'])); c.update(after=copy.deepcopy(s['dialogue']),reply=s['messages'][-1]['text']); print(c['name'],'ok',flush=True)
 except Exception as e: c['errorType']=type(e).__name__; save(); break
 save()
report['current']='finish'
try:
 s.update(service.finish(s)); report['finished']=copy.deepcopy(s); save()
 report['current']='postclass_open'; s.update(service.start_postclass(s)); report['postclassOpen']=copy.deepcopy(s); save()
 report['current']='postclass_answer'; s.update(service.postclass_turn(s,'还是不知道，请帮我继续理解。')); report['postclassAfter']=copy.deepcopy(s)
except Exception as e: report['additionalErrorType']=type(e).__name__
report['current']='done'; save(); print('done',len(report['trace']),flush=True)
