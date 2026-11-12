from pathlib import Path
from copy import deepcopy
import json, os, sys, time
from uuid import uuid4
from dotenv import dotenv_values
ROOT=Path(__file__).resolve().parents[3]; OUT=Path(__file__).parent
sys.path[:0]=[str(ROOT/'student_agent'),str(ROOT/'student_agent/backend/tests')]
config={}
for path in [ROOT/'student_agent/.env.local',ROOT/'platform/.env']:
    for k,v in dotenv_values(path,interpolate=False,encoding='utf-8-sig').items():
        if v is not None:config.setdefault(k,v)
for new,old in [('STUDENT_AGENT_API_KEY','AGENT_LLM_API_KEY'),('STUDENT_AGENT_BASE_URL','AGENT_LLM_BASE_URL'),('STUDENT_AGENT_MODEL','AGENT_LLM_MODEL')]:
    if config.get(new) or config.get(old):os.environ[new]=config.get(new) or config[old]
os.environ.update(LANGSMITH_TRACING='false',LANGCHAIN_TRACING_V2='false',STUDENT_TEST_DATABASE_URL='host=127.0.0.1 port=51080 user=student_p2_test dbname=postgres connect_timeout=5',STUDENT_SERVICE_KEY='recall-five-test-signing',STUDENT_FRESH_SESSION_MODE='1',PLATFORM_TO_STUDENT_KEY='recall-five-isolated')
import conftest
gen=conftest.isolated_database_url.__wrapped__();os.environ['STUDENT_DATABASE_URL']=next(gen)
from backend import main
from backend.infrastructure import persistence
from backend.teaching import service
from fastapi.testclient import TestClient
def save(name,data): (OUT/(name+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def point(id,title,type,details):
    from backend.content.knowledge_schema import compatibility_text
    text=compatibility_text(dict(title=title,type=type,details=details))
    return dict(id=id,title=title,type=type,details=details,content=text,description=text)
concept=point('index','数组下标与越界','concept',{'explanation':'int a[5]有5个元素，下标从0开始，合法下标0至4；a[5]是第6个位置，越界。','understandingPoints':['说明下标从0开始','由5个元素推出合法下标0至4','解释a[5]越界的原因']})
memory=point('syntax','for循环三个部分','memory',{'statement':'for包括初始化、条件判断和更新。','requiredElements':['初始化','条件判断','更新']})
design=json.loads((ROOT/'student_agent/backend/tests/fixtures/array_design_task.json').read_text(encoding='utf-8'))
cases=[('concept-next-point',[concept,memory],['不知道','还是不知道','没理解，你换个说法','还是不会','为什么a[5]越界？请直接解释，不要让我重复你的话。']),
       ('memory-last-correct',[memory],['初始化，其他不知道','还不知道','不会','还是不会','for包括初始化、条件判断和更新。初始化设置初值，条件判断决定是否继续，更新在循环体后执行。']),
       ('design-reinforce',[design],['不知道怎么写','不会','还是不会','不知道','循环下标应该到哪里结束？请直接讲清，不要让我复述。'])]
try:
 for name,points,answers in cases:
    sid='recall-five-'+uuid4().hex
    persistence.save({'id':sid,'phase':'video','lessonId':'lesson','classroomId':'room','context':{'userId':'student','courseId':'course','publication':{'id':'pub','version':1}},'videoRevision':'revision','messages':[],'courses':[],'preparation':'ready','dialogue':service.new_dialogue(points)},0)
    client=TestClient(main.app,headers={'X-Platform-Learning-Key':'recall-five-isolated','X-Platform-Protocol':'platform-cookie-v1','X-Platform-User-Id':'student','X-Platform-Course-Id':'course'})
    def send(kind,text=None):
        before=client.get(f'/api/session/{sid}').json();start=time.monotonic()
        body={'commandId':uuid4().hex,'type':kind,'payload':{'text':text} if text else {},'expectedStateVersion':before['stateVersion'],'contentGeneration':before['contentGeneration']}
        r=client.post(f'/api/session/{sid}/commands',json=body);data=r.json()
        trace={'request':body,'http':r.status_code,'response':data,'elapsed':round(time.monotonic()-start,2)}
        n=len(list(OUT.glob(name+'-command-*.json')));save(f'{name}-command-{n:02}',trace)
        if r.status_code!=200: raise RuntimeError(f'{name} command failed {r.status_code}')
        state=persistence.restore(sid)['dialogue'];save(f'{name}-state-{n:02}',state)
        print(name,kind,'round',n,'stage',state['stage'],'recall',[(p['recall_attempts'],p['status']) for p in state['points']],flush=True)
        return data['sessionView'],state
    send('start_discussion')
    for answer in answers:view,state=send('submit_answer',answer)
    save(name+'-summary',{'stage':state['stage'],'points':[{k:p.get(k) for k in ['id','status','recall_attempts','reinforce_attempts','recall_done','known_parts','gaps','requirements']} for p in state['points']],'reply':view['messages'][-1]['text']})
    send('finish')
finally:
    try:next(gen)
    except StopIteration:pass
