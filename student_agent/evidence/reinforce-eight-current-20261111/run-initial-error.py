from pathlib import Path
import os,sys,json,copy,importlib.util,time
from uuid import uuid4
from dotenv import dotenv_values
ROOT=Path.cwd(); OUT=ROOT/'student_agent/evidence/reinforce-eight-current-20261111'
sys.path.insert(0,str(ROOT/'student_agent'))
config={}
for path in [ROOT/'student_agent/.env.local',ROOT/'platform/.env']:
 for k,v in dotenv_values(path,interpolate=False,encoding='utf-8-sig').items():
  if v is not None:config.setdefault(k,v)
for n,o in [('STUDENT_AGENT_API_KEY','AGENT_LLM_API_KEY'),('STUDENT_AGENT_BASE_URL','AGENT_LLM_BASE_URL'),('STUDENT_AGENT_MODEL','AGENT_LLM_MODEL')]:
 if config.get(n) or config.get(o):os.environ[n]=config.get(n) or config[o]
os.environ['LANGSMITH_TRACING']=os.environ['LANGCHAIN_TRACING_V2']='false'
os.environ['STUDENT_TEST_DATABASE_URL']='host=127.0.0.1 port=51080 user=student_p2_test dbname=postgres connect_timeout=5'
spec=importlib.util.spec_from_file_location('testconf',ROOT/'student_agent/backend/tests/conftest.py'); conf=importlib.util.module_from_spec(spec);spec.loader.exec_module(conf)
gen=conf.isolated_database_url.__wrapped__();os.environ['STUDENT_DATABASE_URL']=next(gen)
os.environ['PLATFORM_TO_STUDENT_KEY']='reinforce-boundary-forward';os.environ['STUDENT_SERVICE_KEY']='isolated-boundary-key'
from fastapi.testclient import TestClient
from backend import main
from backend.infrastructure import persistence
from backend.teaching import service
client=TestClient(main.app,headers={'X-Platform-Learning-Key':'reinforce-boundary-forward','X-Platform-Protocol':'platform-cookie-v1','X-Platform-User-Id':'student','X-Platform-Course-Id':'course'})
def save(n,d):
 (OUT/(n+'.json')).write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
def seed(label,dialogue,messages):
 sid='reinforce-'+uuid4().hex
 persistence.save({'id':sid,'phase':'video','lessonId':'lesson','classroomId':'room','context':{'userId':'student','courseId':'course','publication':{'id':'pub','version':1}},'videoRevision':'revision','messages':messages,'courses':[],'preparation':'ready','dialogue':dialogue},0)
 return sid
counter=0
def command(sid,kind,text=None):
 global counter
 view=client.get('/api/session/'+sid).json();start=time.monotonic()
 body={'commandId':uuid4().hex,'type':kind,'payload':{'text':text} if text else {},'expectedStateVersion':view['stateVersion'],'contentGeneration':view['contentGeneration']}
 response=client.post('/api/session/'+sid+'/commands',json=body);data=response.json();counter+=1
 save(f'{counter:02}-{kind}',{'input':body,'http':response.status_code,'response':data,'elapsed':time.monotonic()-start})
 print(counter,kind,response.status_code,flush=True)
 if response.status_code!=200:raise RuntimeError('command failed; see saved trace')
 result=data['sessionView'];snapshot=persistence.restore(sid);save(f'{counter:02}-snapshot',snapshot['dialogue'])
 print(result['messages'][-1]['text'],flush=True)
 return result,snapshot
try:
 # Original published arrays point and actual wrong answer are from the prior full PPT run.
 source=json.loads((ROOT/'student_agent/evidence/arrays-e2e-2026-11-11/snapshot-turn07.json').read_text(encoding='utf-8'))['dialogue']
 point=copy.deepcopy(source['points'][-1]); actual=point['assessment_history'][-1]
 point.update(recall_done=True,reinforce_done=False,reinforcement_required=True,recall_attempts=5,reinforce_attempts=0,attempts=5)
 point['assessment_history']=[dict(copy.deepcopy(actual),round=i+1,stage='recall') for i in range(5)]
 state=service.new_dialogue([point]);state['points']=[point];state.update(stage='reinforce',last_point_id=point['id'],evaluation={'intent':'answer','assessments':[]},student_text=actual['studentText'])
 save('seed',{'notice':'Five recall entries are duplicated seeded history, not five live calls. Point/answer originated from actual published arrays lesson.','dialogue':state})
 sid=seed('eight',state,[]);view,snap=command(sid,'start_discussion')
 pre8=None
 for i in range(8):
  if i==7:pre8=copy.deepcopy(snap)
  answer='我不知道，还是不会，请换个方式帮我。' if i!=3 else '我只知道int a[5]有5个int元素，循环怎么写还是不会。'
  if i==7:answer='还是不知道。请直接讲清楚为什么i<=5会越界、应该怎么改，不要直接跳过我的问题。'
  view,snap=command(sid,'submit_answer',answer)
 save('exhausted-check',{'stage':snap['dialogue']['stage'],'attempts':snap['dialogue']['points'][0]['reinforce_attempts'],'status':snap['dialogue']['points'][0]['status'],'completionReason':snap['dialogue'].get('completion_reason')})
 command(sid,'finish');continued,after=command(sid,'continue_after_class');repeated,_=command(sid,'continue_after_class')
 save('reentry-check',{'messagesUnchanged':continued['messages']==repeated['messages']})
 command(sid,'finish');command(sid,'continue_after_class')
 # Separate seeded round-seven branch to check an actual correct eighth answer.
 posid=seed('correct8',pre8['dialogue'],pre8['messages']);command(posid,'start_discussion')
 correct='int a[5]; int i; for(i=0;i<5;i++){a[i]=i+i+1;} i取0、1、2、3、4，对应全部合法下标，无a[5]，最终1、3、5、7、9，5项全是奇数，每项恰好赋值一次。'
 good,goodstate=command(posid,'submit_answer',correct)
 save('correct-eighth-check',{'stage':goodstate['dialogue']['stage'],'status':goodstate['dialogue']['points'][0]['status'],'attempts':goodstate['dialogue']['points'][0]['reinforce_attempts']})
 command(posid,'finish')
finally:
 try:next(gen)
 except StopIteration:pass
