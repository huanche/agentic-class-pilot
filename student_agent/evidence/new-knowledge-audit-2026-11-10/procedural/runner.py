"""Real teacher and real learner-role calls; archived points, in-memory service only."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

from dotenv import dotenv_values
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / "student_agent"))
from backend.content.knowledge_schema import compatibility_text
from backend.infrastructure import model
from backend.teaching import service, typed_state

OUT = ROOT / "student_agent/evidence/new-knowledge-audit-2026-11-10/procedural"
OUT = OUT / os.environ["AUDIT_RUN"] if os.environ.get("AUDIT_RUN") else OUT
OUT.mkdir(parents=True, exist_ok=True)

config = {}
for base in [ROOT, Path("E:/LMS系统参考/项目/agentic-class-pilot-running")]:
    for name in ["student_agent/.env.local", "platform/.env"]:
        path = base / name
        if path.is_file():
            for key, value in dotenv_values(path, interpolate=False, encoding="utf-8-sig").items():
                if value is not None:
                    config.setdefault(key, value)
for new, old in [("STUDENT_AGENT_API_KEY", "AGENT_LLM_API_KEY"), ("STUDENT_AGENT_BASE_URL", "AGENT_LLM_BASE_URL"), ("STUDENT_AGENT_MODEL", "AGENT_LLM_MODEL")]:
    if not config.get(new) and config.get(old):
        config[new] = config[old]
for key in ["STUDENT_AGENT_API_KEY", "STUDENT_AGENT_BASE_URL", "STUDENT_AGENT_MODEL", "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"]:
    if config.get(key):
        os.environ.setdefault(key, config[key])
os.environ["LANGSMITH_TRACING"] = os.environ["LANGCHAIN_TRACING_V2"] = "false"

source=json.loads((ROOT/'student_agent/docs/knowledge-extraction/validation/2026-11-05-live-model/knowledge-points.json').read_text(encoding='utf-8'))
points=[p for p in source['points'] if p['type']=='design']
cases=[
('valid-alternative',1,['普通字符push；#只pop一次，空栈则忽略；@直接将栈顶指针置为-1而不是循环pop。比如输入ab#cd@xy，ab#后a，cd后acd，@后空，再xy得到xy。整行撤销后栈空。'], 'mastered'),
('partial-then-complete',1,['普通字符push，@清空。','#是退格，只弹出栈顶一个字符，空栈不弹。@把当前行全清空，可以反复pop到空，或者重置栈顶。ab#cd@xy最终xy，@之后栈为空。'], 'mastered'),
('wrong-single-pop',1,['普通字符push，#弹一个，@也弹一个。例如abc@最后ab，栈里是a和b。'], 'not_mastered'),
('prerequisite-missing',0,['我不知道1和0表示什么，栈顶又是什么？能先演示一步吗？'], 'not_mastered'),
('correct-step-derivation',0,['固定按A、B、C入栈。我设计110100：push A得[A]，push B得[A,B]，pop B得[A]，push C得[A,C]，pop C得[A]，pop A得[]，所以出栈BCA。110100是操作序列，BCA是出栈序列。CAB不可能：若先出C就得ABC全入栈，C出后栈顶是B，无法先出A。'], 'mastered'),
('illegal-empty-pop',0,['操作序列010110，先从空栈pop一个A，再push B，pop B，再push C、push D、pop D，所以合法。'], 'not_mastered')]
report={'source':{k:source[k] for k in ['courseId','lessonId','sourceRevision']},'businessCodeChanged':False,'databaseUsed':False,'learner':'scripted synthetic answers, real model teacher','cases':[],'calls':[]}
class Capture(BaseCallbackHandler):
 def on_chat_model_start(self,serialized,messages,*,run_id,**kw):
  entry={'id':str(run_id),'case':active,'messages':[m.model_dump(include={'type','content','tool_calls','tool_call_id','name'}) for m in messages[0]]};report['calls'].append(entry);save()
 def on_llm_end(self,response,*,run_id,**kw):
  entry=next(x for x in report['calls'] if x['id']==str(run_id)); msg=response.generations[0][0].message;entry.update(content=msg.content,toolCalls=msg.tool_calls,usage=msg.usage_metadata);save()
def save(): (OUT/'run.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
teacher=model.teaching_model();teacher.callbacks=[Capture()];model.teaching_model=lambda:teacher
report['model']=teacher.model_name
for active,index,answers,expected in cases:
 if os.environ.get("AUDIT_CASE") and active != os.environ["AUDIT_CASE"]: continue
 point=deepcopy(points[index]);point['content']=point['description']=compatibility_text(point)
 session={'id':'audit-'+active,'phase':'video','lessonId':source['lessonId'],'messages':[],'courses':[],'preparation':'ready','dialogue':service.new_dialogue([point])}
 result={'case':active,'point':point,'expected':expected,'turns':[]};report['cases'].append(result)
 try:
  session.update(service.start_discussion(session));result['opening']=session['messages'][-1]['text']
  for answer in answers:
   if session['dialogue']['stage']=='wrapup':break
   session.update(service.classroom_turn(session,answer)); result['turns'].append({'student':answer,'reply':session['messages'][-1]['text'],'state':deepcopy(session['dialogue'])});save()
  status=session['dialogue']['points'][0]['status'];result.update(status=status,passed=(status=='mastered')==(expected=='mastered'))
 except Exception as e:result.update(errorType=type(e).__name__)
 save();print(json.dumps({k:result.get(k) for k in ['case','status','passed','errorType']},ensure_ascii=False),flush=True)
