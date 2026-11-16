from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'student_agent'))
from backend.teaching import service, typed_state, typed_teaching
from backend.infrastructure import model

for base in [ROOT, Path('E:/LMS系统参考/项目/agentic-class-pilot-running')]:
    for rel in ['student_agent/.env.local', 'platform/.env']:
        p = base / rel
        if not p.exists():
            continue
        config = dotenv_values(p, encoding='utf-8-sig', interpolate=False)
        for key, fallback in [('STUDENT_AGENT_API_KEY', 'AGENT_LLM_API_KEY'),
                              ('STUDENT_AGENT_BASE_URL', 'AGENT_LLM_BASE_URL'),
                              ('STUDENT_AGENT_MODEL', 'AGENT_LLM_MODEL')]:
            value = config.get(key) or config.get(fallback)
            if value:
                os.environ.setdefault(key, value)
os.environ['LANGSMITH_TRACING'] = os.environ['LANGCHAIN_TRACING_V2'] = 'false'
source = json.loads(Path(__file__).with_name('dialogue.json').read_text(encoding='utf-8'))

def before_turn(index):
    state = service.new_dialogue(source['points'])
    history = source['points'][0]['assessment_history']
    for i in range(index + 1):
        h = history[i]
        point = state['points'][0]
        point.update(latest_question=h['question'], question_targets=h['target_ids'])
        point['task_question'] = point['task_question'] or h['question']
        record = {'stage': 'recall', 'text': h['question'], 'target_ids': h['target_ids'], 'planned_action': 'ask'}
        point['question_history'].append(deepcopy(record))
        point['help_history'].append(deepcopy(record))
        state['student_text'] = h['studentText']
        if i < index:
            state = typed_state.advance(state, 'answer', h['answer_assessment'])
    return state

output = Path(os.environ.get('REPLAY_OUTPUT', str(Path(__file__).with_name('replay.json'))))
report = {'model': model.teaching_model().model_name, 'cases': []}
for index, name in [(3, 'cumulative-answer'), (4, 'explain-before-switch'), (0, 'terms-only')]:
    state = before_turn(index)
    if name == 'terms-only':
        state['student_text'] = '栈是LIFO，队列是FIFO。'
    result = typed_teaching.run(state)
    entry = {'name': name, 'before': state, 'after': result}
    report['cases'].append(entry)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(name, 'requirement=', result['points'][0]['requirements'][1]['status'], flush=True)
    print(result['reply'], flush=True)
if report['cases'][0]['after']['points'][0]['requirements'][1]['status'] != 'demonstrated':
    raise SystemExit(1)
if report['cases'][2]['after']['points'][0]['requirements'][1]['status'] == 'demonstrated':
    raise SystemExit(1)
closing = report['cases'][1]['after']['reply']
if not all(term in closing for term in ['C', '栈顶', 'A', '队头']):
    raise SystemExit('Closing did not answer the specific captured question; inspect reply manually')
