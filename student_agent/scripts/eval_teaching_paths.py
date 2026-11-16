"""Real-model multi-turn in-memory paths; JSON round-trip simulates snapshot reload."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

from eval_teaching_behavior import ROOT, load_config

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    parser.add_argument('--workers',type=int,default=3)
    args=parser.parse_args()
    if args.workers < 1:
        parser.error('workers must be positive')
    load_config()
    from teaching_behavior_paths import PATHS, CONTENT, NEXT
    from backend.content.knowledge import compile_points
    from backend.content.knowledge_schema import submit_knowledge_points
    from backend.teaching import typed_state, typed_teaching
    out=Path(args.output).resolve()
    out.mkdir(parents=True,exist_ok=True)
    if (out/'metadata.json').exists():
        raise ValueError('Choose a new output directory')
    code=[ROOT/'student_agent/backend/teaching/typed_teaching.py',ROOT/'student_agent/backend/teaching/typed_state.py',
          ROOT/'student_agent/backend/tests/teaching_behavior_paths.py',Path(__file__)]
    (out/'metadata.json').write_text(json.dumps({'paths':18,'workers':args.workers,
        'scope':'real generated multi-turn tutor; synthetic learner; in-memory; not database/HTTP recovery',
        'code_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in code}},indent=2),encoding='utf-8')
    def run(spec):
        state=typed_state.initial(compile_points(submit_knowledge_points(points=[CONTENT[spec['kind']],NEXT])))
        report={'path':spec,'turns':[],'failures':[]}
        start=time.monotonic()
        after_class=False
        try:
            state=typed_teaching.run(state,opening=True)
            report['opening']=deepcopy(state)
            for step,text in enumerate(spec['answers'],1):
                if step==spec['resume_at']:
                    # Exercise reopening with the actual saved tutor/learner
                    # history; no scripted tutor reply replaces that history.
                    state=json.loads(json.dumps(state,ensure_ascii=False))
                    after_class=True
                    state=typed_teaching.run(state,opening=True,after_class=True)
                    report['resume']=deepcopy(state)
                if not typed_state.current(state,after_class=after_class):
                    report['failures'].append(f'ended before learner step {step}')
                    break
                before=deepcopy(state)
                state['student_text']=text
                state=typed_teaching.run(state,after_class=after_class)
                mastered=state['points'][0]['status']=='mastered'
                failures=[]
                if mastered != (step>=spec['master_at']):
                    failures.append('original point mastery differs from cumulative student evidence')
                report['turns'].append({'step':step,'student':text,'before':before,'after':deepcopy(state),'failures':failures})
                report['failures'].extend(f'step {step}: {f}' for f in failures)
                (out/(spec['id']+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            if spec['all_done'] and not all(p['status']=='mastered' for p in state['points']):
                report['failures'].append('path did not complete both points')
        except Exception as error:
            report['error_type']=type(error).__name__
            report['failures'].append('execution_error')
        report['elapsed_seconds']=round(time.monotonic()-start,3)
        (out/(spec['id']+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        return {'id':spec['id'],'turns':len(report['turns']),'failures':report['failures']}
    rows=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for future in as_completed([pool.submit(run,spec) for spec in PATHS]):
            row=future.result();rows.append(row)
            (out/'summary.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(row),flush=True)
    sys.exit(1 if any(r['failures'] for r in rows) else 0)

if __name__=='__main__':
    main()
