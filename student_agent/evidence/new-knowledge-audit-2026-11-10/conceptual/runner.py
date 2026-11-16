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

OUT = ROOT / "student_agent/evidence/new-knowledge-audit-2026-11-10/conceptual"
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
report={'source':{k:source[k] for k in ['courseId','lessonId','sourceRevision']},'codeSha256':hashlib.sha256((ROOT/'student_agent/backend/teaching/typed_teaching.py').read_bytes()).hexdigest(),'trace':[],'cases':[]}
active={}
class Capture(BaseCallbackHandler):
 def on_chat_model_start(self,serialized,messages,*,run_id,**kwargs):
  item={'case':current_id,'messages':[m.model_dump(include={'type','content','tool_calls','tool_call_id','name'}) for m in messages[0]]}; report['trace'].append(item); active[str(run_id)]=item
 def on_llm_end(self,response,*,run_id,**kwargs):
  msg=response.generations[0][0].message; active[str(run_id)].update(content=msg.content,toolCalls=msg.tool_calls,usage=msg.usage_metadata)
 def on_llm_error(self,error,*,run_id,**kwargs): active[str(run_id)].update(errorType=type(error).__name__)
teacher=model.teaching_model(); teacher.callbacks=[Capture()]; model.teaching_model=lambda:teacher
report['model']=teacher.model_name
cases=[
 ('memory-equivalent',0,['栈和队列都是操作受限的线性表，不能随意在中间增删。栈在同一个栈顶插入删除，后进去先出来，也就是LIFO；队列在rear队尾添加、front队头移除，先进去先出来FIFO。']),
 ('memory-incomplete',0,['栈后进先出，队列先进先出。']),
 ('memory-confusion',0,['栈在队尾插入，在队头删除，遵循先进先出。队列在同一端增删，后进先出。']),
 ('concept-conclusion-only',7,['用循环队列解决假溢出。']),
 ('concept-causal',7,['顺序队列front前移后，前部有空位，但rear到数组末端时不能直接再加一，造成明明有空位却误认为满。把数组逻辑上首尾相接，rear和front按容量取模移动，才能回到前面复用空位。为区别空和满，留一个空位，空时rear等于front，满时(rear+1)%MaxSize==front。']),
 ('concept-repetition',7,['用循环队列解决假溢出。','用循环队列解决假溢出。','用循环队列解决假溢出。'])]
if os.environ.get('AUDIT_CASE'): cases=[c for c in cases if c[0]==os.environ['AUDIT_CASE']]
for current_id,index,answers in cases:
 p=deepcopy(source['points'][index]); p['content']=p['description']=compatibility_text(p)
 session={'id':current_id,'phase':'video','lessonId':source['lessonId'],'videoRevision':source['sourceRevision'],'messages':[],'courses':[],'preparation':'ready','dialogue':service.new_dialogue([p])}
 item={'id':current_id,'point':p,'turns':[]}; report['cases'].append(item)
 try:
  session.update(service.start_discussion(session)); item['opening']=session['messages'][-1]['text']
  for answer in answers:
   if session['dialogue']['stage']=='wrapup':break
   before=deepcopy(session['dialogue']); session.update(service.classroom_turn(session,answer))
   item['turns'].append({'answer':answer,'reply':session['messages'][-1]['text'],'before':before,'after':deepcopy(session['dialogue'])})
  item['status']='completed'
 except Exception as e: item.update(status='error',errorType=type(e).__name__)
 (OUT/os.environ.get('AUDIT_OUTPUT','run.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'case':current_id,'status':item['status'],'turns':len(item['turns'])}),flush=True)
