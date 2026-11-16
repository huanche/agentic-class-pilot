"""Real archived course, real teacher/extractor; no persistence or publication."""
from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'student_agent'))
from backend.teaching import service, typed_teaching
from backend.content import knowledge
from backend.content.context import classroom_materials
from backend.content.prompts import KNOWLEDGE_EXTRACTION_PROMPT
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
output = Path(os.environ['WHOLE_POINT_OUTPUT'])
assert not output.exists(), 'Use a new output path'
report = {'productionWrites': False, 'model': model.teaching_model().model_name}
if os.environ.get('WHOLE_POINT_PHASE') == 'extract':
    source = json.loads((ROOT / '.runtime/typed-knowledge-live/source.json').read_text(encoding='utf-8'))
    materials = classroom_materials(source['scenes'])
    report.update(prompt=KNOWLEDGE_EXTRACTION_PROMPT, materialCount=len(materials))
    result = knowledge.learning_points(materials, 'local-comparison', 'stack-queue')
    report.update(asdict(result))
else:
    original = json.loads((ROOT / 'student_agent/evidence/stack-dialogue-2026-11-11/dialogue.json').read_text(encoding='utf-8'))
    report['cases'] = []
    cases = [
        ('memory-complete', 1, ['栈是只在一端插入和删除的线性表。允许操作的一端叫栈顶Top，另一端栈底Bottom不允许插入删除。Push在栈顶插入，Pop删除栈顶元素。最后入栈的元素最先出栈，即LIFO。']),
        ('concept-complete', 0, ['普通线性表可以任意位置增删；栈只能在栈顶入出，最后放进去的就在栈顶只能先取，所以后进先出。队列队尾插入队头删除，最先进去的在队头先取，所以先进先出。比如ABC依次放入，栈全取为CBA，队列为ABC。']),
        ('design-complete', 10, ['A、B、C固定依次入栈。1是Push、0是Pop，设计110100：push A栈[A]，push B栈[A,B]，pop B栈[A]输出B，push C栈[A,C]，pop C栈[A]输出BC，pop A栈空输出BCA。每步只删栈顶，因此符合LIFO。CAB不可能，先出C必须ABC都入栈，C出后栈顶是B，不能跳过B先取A。']),
        ('memory-partial', 1, ['栈是只在栈顶进行插入删除的线性表。', '允许操作的一端叫Top，另一端Bottom不允许操作。Push栈顶插入、Pop栈顶删除，最后放入的先取出，是LIFO。']),
        ('concept-help', 0, ['我不懂位置限制为什么会决定顺序，你直接讲清楚吧。']),
    ]
    for name, index, answers in cases:
        if os.environ.get('WHOLE_POINT_CASES') and name not in os.environ['WHOLE_POINT_CASES'].split(','):
            continue
        state = service.new_dialogue([original['points'][index]])
        entry = {'name': name, 'point': deepcopy(state['points'][0]), 'turns': []}
        report['cases'].append(entry)
        state = typed_teaching.run(state, opening=True)
        entry['opening'] = state['reply']
        print(name, 'opening:', state['reply'], flush=True)
        if name == 'design-complete':
            # Keep the answer paired with its actual archived ABC task. The
            # newly generated opening above is reviewed separately for breadth.
            archived = json.loads((ROOT / 'student_agent/evidence/new-knowledge-audit-2026-11-10/procedural/run.json').read_text(encoding='utf-8'))
            case = next(c for c in archived['cases'] if c['case'] == 'correct-step-derivation')
            state = service.new_dialogue([original['points'][index]])
            focus = state['points'][0]
            focus.update(task_question=case['opening'], latest_question=case['opening'],
                         question_targets=[r['id'] for r in focus['requirements']])
            focus['question_history'].append({'stage':'recall', 'text':case['opening'],
                                             'target_ids':focus['question_targets'], 'planned_action':'ask'})
            entry['answerTask'] = case['opening']
        for answer in answers:
            if state['stage'] == 'wrapup':
                break
            state['student_text'] = answer
            state = typed_teaching.run(state)
            entry['turns'].append({'student': answer, 'state': deepcopy(state)})
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(name, 'status:', state['points'][0]['status'], 'reply:', state['reply'], flush=True)
        entry['passed'] = (state['points'][0]['status'] == 'mastered') if name != 'concept-help' else state['points'][0]['status'] != 'mastered'
output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
if 'cases' in report and not all(c['passed'] for c in report['cases']):
    raise SystemExit(1)
