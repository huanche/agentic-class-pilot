"""Opt-in real-model baseline; synthetic in-memory sessions, no database writes.

Run from repository root with student_agent/.venv/Scripts/python.exe.
Outputs contain synthetic conversation/evidence only; never credentials or headers.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from threading import local

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'student_agent'), str(ROOT/'student_agent/backend/tests')]

def load_config():
    from dotenv import dotenv_values
    values = {}
    for file in [ROOT/'student_agent/.env.local', ROOT/'platform/.env']:
        for key, value in dotenv_values(file, interpolate=False, encoding='utf-8-sig').items():
            if value is not None:
                values.setdefault(key, value)
    for new, old in [('STUDENT_AGENT_API_KEY','AGENT_LLM_API_KEY'), ('STUDENT_AGENT_BASE_URL','AGENT_LLM_BASE_URL'), ('STUDENT_AGENT_MODEL','AGENT_LLM_MODEL')]:
        if not os.environ.get(new) and (values.get(new) or values.get(old)):
            os.environ[new] = values.get(new) or values[old]
    os.environ.update(LANGSMITH_TRACING='false', LANGCHAIN_TRACING_V2='false')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--ids', default='')
    parser.add_argument('--high-repeats', type=int, default=5)
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--repeat-all', type=int, default=1)
    parser.add_argument('--capture-messages', action='store_true', help='Capture synthetic model messages and responses, never HTTP headers')
    args = parser.parse_args()
    if min(args.high_repeats, args.repeat_all, args.workers) < 1:
        parser.error('Repeat counts and workers must be positive')
    load_config()
    from teaching_behavior_cases import CASES, build_case, check_state
    from backend.teaching import typed_teaching
    from backend.infrastructure import model
    from langchain_core.callbacks import BaseCallbackHandler
    trace = local()
    class Capture(BaseCallbackHandler):
        def __init__(self, events):
            self.events = events
        def on_chat_model_start(self, serialized, messages, **kwargs):
            self.events.append({'request': [[{'role':m.type,'content':m.content} for m in batch] for batch in messages]})
        def on_llm_end(self, response, **kwargs):
            self.events.append({'response': [{'text':g.message.content,'tool_calls':g.message.tool_calls} for batch in response.generations for g in batch]})
    original_model = model.teaching_model
    if args.capture_messages:
        def captured_model():
            client = original_model()
            client.callbacks = [*(client.callbacks or []), Capture(trace.events)]
            return client
        model.teaching_model = captured_model
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output/'metadata.json').exists():
        raise ValueError('Output already contains a run; choose a new directory to preserve evidence')
    selected = [c for c in CASES if not args.ids or c['id'] in args.ids.split(',')]
    if not selected:
        raise ValueError('No scenarios selected')
    def run(spec, trial):
        name = f"{spec['id']}-{trial:02}"
        state = build_case(spec)
        record = dict(id=spec['id'], trial=trial, case=spec, before=deepcopy(state))
        start = time.monotonic()
        trace.events = []
        try:
            result = typed_teaching.run(state, after_class=spec.get('after_class', False))
            record.update(after=result, state_failures=check_state(spec, state, result))
        except Exception as error:
            # Exception messages can include provider details; retain type only.
            record.update(error_type=type(error).__name__, state_failures=['execution_error'])
        record['elapsed_seconds'] = round(time.monotonic()-start, 3)
        if args.capture_messages:
            record['model_events'] = trace.events
        (output/f'{name}.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        return {key:record[key] for key in ['id','trial','state_failures','elapsed_seconds']}
    jobs = [(c, n) for c in selected for n in range(1, max(args.repeat_all, args.high_repeats if c.get('high') else 1)+1)]
    metadata = dict(started_utc=datetime.now(timezone.utc).isoformat(), model=os.environ.get('STUDENT_AGENT_MODEL') or os.environ.get('LLM_MODEL') or 'deepseek-v4-flash',
                    code_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'student_agent/backend/teaching/typed_teaching.py', ROOT/'student_agent/backend/teaching/typed_state.py', Path(__file__), ROOT/'student_agent/backend/tests/teaching_behavior_cases.py']},
                    scenario_count=len(selected), run_count=len(jobs), workers=args.workers,
                    scope='synthetic in-memory real-model baseline; not HTTP/persistence; semantic review separate')
    (output/'metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run, c, n) for c, n in jobs]
        for future in as_completed(futures):
            row = future.result()
            results.append(row)
            (output/'summary.json').write_text(json.dumps(sorted(results,key=lambda r:(r['id'],r['trial'])),ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(row), flush=True)
    return 1 if any(r['state_failures'] for r in results) else 0

if __name__ == '__main__':
    sys.exit(main())
