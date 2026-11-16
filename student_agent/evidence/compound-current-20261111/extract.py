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
from backend.content import knowledge
from backend.content.context import classroom_materials
source=json.loads((ROOT/'.runtime/typed-knowledge-live/source.json').read_text(encoding='utf-8'))
materials=classroom_materials(source['scenes'])
result=knowledge.learning_points(materials,source['courseId'],source['lessonId'])
(OUT/'fresh-extraction.json').write_text(json.dumps({'source':{k:source[k] for k in ['courseId','lessonId','sourceRevision']},'materials':materials,'points':result.points},ensure_ascii=False,indent=2),encoding='utf-8')
print('extracted',len(result.points),'points',flush=True)
for p in result.points:
 if '链' in p['title']:print(json.dumps(p,ensure_ascii=False),flush=True)
