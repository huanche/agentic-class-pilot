from pathlib import Path
from copy import deepcopy
import json,os,sys,importlib.util
from uuid import uuid4
from dotenv import dotenv_values
ROOT=Path.cwd();OUT=ROOT/'student_agent/evidence/compound-current-20261111'
sys.path.insert(0,str(ROOT/'student_agent'))
cfg={}
for path in [ROOT/'student_agent/.env.local',ROOT/'platform/.env']:
 for k,v in dotenv_values(path,interpolate=False,encoding='utf-8-sig').items():
  if v is not None:cfg.setdefault(k,v)
for new,old in [('STUDENT_AGENT_API_KEY','AGENT_LLM_API_KEY'),('STUDENT_AGENT_BASE_URL','AGENT_LLM_BASE_URL'),('STUDENT_AGENT_MODEL','AGENT_LLM_MODEL')]:
 if cfg.get(new) or cfg.get(old):os.environ.setdefault(new,cfg.get(new) or cfg[old])
os.environ['LANGSMITH_TRACING']=os.environ['LANGCHAIN_TRACING_V2']='false'
os.environ['STUDENT_TEST_DATABASE_URL']='host=127.0.0.1 port=51080 user=student_p2_test dbname=postgres connect_timeout=5'
spec=importlib.util.spec_from_file_location('fixtureconfig',ROOT/'student_agent/backend/tests/conftest.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
gen=mod.isolated_database_url.__wrapped__();os.environ['STUDENT_DATABASE_URL']=next(gen)
os.environ['STUDENT_SERVICE_KEY']='compound-disposable-signing';os.environ['STUDENT_FRESH_SESSION_MODE']='1';os.environ['PLATFORM_TO_STUDENT_KEY']='compound-local-forward'
from backend import main
from backend.infrastructure import persistence,model
from fastapi.testclient import TestClient
from langchain_core.callbacks import BaseCallbackHandler
saved=json.loads((ROOT/'student_agent/docs/knowledge-teaching/validation/2026-11-10-requirement-progress/run.json').read_text(encoding='utf-8'));turn=saved['turns'][5]
summary=[];trace=[]
class Capture(BaseCallbackHandler):
 def on_chat_model_start(self,serialized,messages,**kw):trace.append({'messages':[m.model_dump(include={'type','content','tool_calls','tool_call_id'}) for m in messages[0]]})
 def on_llm_end(self,response,**kw):
  m=response.generations[0][0].message;trace[-1].update(content=m.content,toolCalls=m.tool_calls)
original=model.teaching_model
def clientmodel():
 c=original();c.callbacks=[Capture()];return c
model.teaching_model=clientmodel
client=TestClient(main.app,headers={'X-Platform-Learning-Key':'compound-local-forward','X-Platform-Protocol':'platform-cookie-v1','X-Platform-User-Id':'student','X-Platform-Course-Id':'course'})
cases=['archived-1','archived-2','current-1','current-2','complete','prior-evidence','other-items-confirmed']
try:
 for case in os.environ.get('COMPOUND_CASES', ','.join(cases)).split(','):
  trace.clear();state=deepcopy(turn['stateBefore']);point=state['points'][1];answer=turn['student']
  if not case.startswith('archived'):state['reply_version']=1
  if case=='complete':answer+='入队要把新结点链接在rear所指尾结点之后，再把rear更新为新尾结点。'
  if case.startswith('prior-evidence'):
   item=point['requirements'][1];item.update(status='unconfirmed',evidence='',studentText='',gap='');point['known_parts']=['入队在rear之后插入新结点，再更新rear。']
   point['assessment_history']=[{'stage':'recall','round':1,'result':'partial','evidence':'已说明入队位置','studentText':'把新结点链接在rear之后，再更新rear。','question':'链队列怎样入队？'}]
  if case=='other-items-confirmed':
   for item in point['requirements']:
    if item['id']!='understandingPoints:2':item.update(status='demonstrated',evidence='受控前置：此前完整回答该项。',studentText='本例仅测试剩余复合项，其余条目预置已确认。',gap='')
  sid='compound-'+uuid4().hex
  seed={'id':sid,'phase':'discussion','lessonId':'lesson','classroomId':'room','context':{'userId':'student','courseId':'course','publication':{'id':'pub','version':1}},'videoRevision':'revision','messages':[{'role':'assistant','text':m['text'],'phase':m.get('phase','recall')} for m in saved['session']['messages'][:11] if m['role']=='assistant'],'courses':[],'preparation':'ready','dialogue':state}
  persistence.save(seed,0)
  view=client.get(f'/api/session/{sid}').json()
  body={'commandId':uuid4().hex,'type':'submit_answer','payload':{'text':answer},'expectedStateVersion':view['stateVersion'],'contentGeneration':view['contentGeneration']}
  r=client.post(f'/api/session/{sid}/commands',json=body);result=r.json()
  after=persistence.restore(sid)['dialogue'];p=after['points'][1];item=p['requirements'][1]
  record={'case':case,'student':answer,'before':state,'httpStatus':r.status_code,'response':result,'after':after,'item':item,'trace':deepcopy(trace)}
  (OUT/(case+'.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
  row={'case':case,'httpStatus':r.status_code,'itemStatus':item['status'],'pointStatus':p['status'],'stage':after['stage']};summary.append(row);print(json.dumps(row),flush=True)
  (OUT/('summary-'+os.environ.get('COMPOUND_CASES','all')+'.json')).write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
finally:
 try:next(gen)
 except StopIteration:pass
