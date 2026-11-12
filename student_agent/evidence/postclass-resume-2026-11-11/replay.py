"""Real-provider replay of archived lesson state; no stored session is modified."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'student_agent'))
config = {}
for path in [ROOT / 'student_agent/.env.local', ROOT / 'platform/.env']:
    for key, value in dotenv_values(path, interpolate=False, encoding='utf-8-sig').items():
        if value is not None:
            config.setdefault(key, value)
for new, old in [('STUDENT_AGENT_API_KEY', 'AGENT_LLM_API_KEY'),
                 ('STUDENT_AGENT_BASE_URL', 'AGENT_LLM_BASE_URL'), ('STUDENT_AGENT_MODEL', 'AGENT_LLM_MODEL')]:
    if config.get(new) or config.get(old):
        os.environ.setdefault(new, config.get(new) or config[old])
os.environ['LANGSMITH_TRACING'] = os.environ['LANGCHAIN_TRACING_V2'] = 'false'
from backend.teaching import service

source = ROOT / 'student_agent/evidence/arrays-e2e-2026-11-11'
snapshot = json.loads((source / 'early-before-exit.json').read_text(encoding='utf-8'))
resume = json.loads((source / 'early-resume.json').read_text(encoding='utf-8'))
results = []
for case in ['partial', 'unassessed']:
    state = deepcopy(snapshot['dialogue'])
    messages = resume['messages']
    if case == 'unassessed':
        state = service.new_dialogue(state['points'])
        messages = []
    before = deepcopy(state)
    changed = service.start_postclass({'phase': 'done', 'dialogue': state, 'messages': messages})
    point = changed['dialogue']['points'][0]
    original = before['points'][0]
    checks = {key: point[key] == original[key] for key in
              ['requirements', 'assessment_history', 'recall_attempts', 'reinforce_attempts']}
    checks['input_not_mutated'] = state == before
    result = {'case': case, 'reply': changed['messages'][-1]['text'], 'checks': checks}
    results.append(result)
    Path(__file__).with_name('results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False), flush=True)
    assert all(checks.values())
