"""Persist with the candidate and recover using a separately imported release.

Set STUDENT_RELEASE_FALLBACK_ROOT to include the prepared fallback worktree.
Only the external model is scripted; persistence and teaching executors are real.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest
from teaching_behavior_cases import CASES, build_case
from backend.infrastructure import persistence
from backend.teaching import service

ROOT = Path(__file__).resolve().parents[3]
READERS = [ROOT] + ([Path(os.environ['STUDENT_RELEASE_FALLBACK_ROOT'])]
                   if os.environ.get('STUDENT_RELEASE_FALLBACK_ROOT') else [])
CHILD = r'''
import json, sys
from langchain_core.messages import AIMessage
from backend.infrastructure import persistence, model
from backend.teaching import progression, service, typed_state
from test_typed_teaching import ScriptedModel
sid, should_continue = sys.argv[1:]
session = persistence.restore(sid)
before = json.loads(json.dumps(session['dialogue']))
normalized = progression.normalize(before)
assert normalized == before
if should_continue == 'yes':
    point = typed_state.current(before)
    updates = [{'requirement_id': r['id'], 'status': 'demonstrated',
                'evidence': '学生准确说明数组名和元素个数', 'gap': ''}
               for r in point['requirements'] if r['status'] != 'demonstrated']
    packet = AIMessage(content='', tool_calls=[{'name': 'submit_current_assessment', 'id': 'resume',
        'args': {'intent': 'answer', 'assessment': {'answer_result': 'correct',
            'evidence': '已有学生证据与本轮答案完整覆盖原要求', 'updates': updates, 'next_step': ''}}}])
    client = ScriptedModel(responses=[packet, AIMessage(content='这部分已完成，我们继续看数组连续存放。')])
    model.teaching_model = lambda: client
    count = len(session['messages'])
    session.update(service.classroom_turn(session, 'a是数组名，5表示元素个数。'))
    persistence.save(session, count)
    restored = persistence.restore(sid)
    assert restored['dialogue']['flow_version'] == 4
    assert restored['dialogue']['points'][0]['status'] == 'mastered'
    assert restored['dialogue']['recall_round_limit'] == before['recall_round_limit']
    assert restored['dialogue']['reinforce_round_limit'] == before['reinforce_round_limit']
    assert len(restored['dialogue']['points'][0]['assessment_history']) == len(before['points'][0]['assessment_history']) + 1
    restored.update(service.finish(restored))
    assert restored['feedback']['typedTeaching'] is True
    persistence.save(restored, len(restored['messages']))
    assert persistence.restore(sid)['feedback'] == restored['feedback']
print(json.dumps({'ok': True, 'flowVersion': before['flow_version']}))
'''


@pytest.mark.parametrize('reader', READERS, ids=lambda p: p.name)
@pytest.mark.parametrize('case', ['legacy', '22', '09', '19', 'postclass'])
def test_candidate_snapshots_survive_release_switch(pg, reader, case):
    if case == 'legacy':
        dialogue = service.new_dialogue([{'id': 'legacy-point', 'title': '旧课', 'content': '旧课程内容'}])
        assert dialogue['flow_version'] == 3
    else:
        spec = next(c for c in CASES if c['id'] == ('49' if case == 'postclass' else case))
        dialogue = build_case(spec)
        if case == '22':
            point = dialogue['points'][0]
            point['requirements'][0].update(status='demonstrated', evidence='int表示元素类型', studentText='int表示元素类型')
            point['status'] = 'partial'
            point['assessment_history'] = [{'stage': 'recall', 'result': 'partial', 'studentText': 'int表示元素类型'}]
        if case == 'postclass':
            dialogue['postclass_point_id'] = dialogue['points'][1]['id']
    sid = 'release-recovery-' + uuid4().hex
    saved = {'id': sid, 'phase': 'done' if case == 'postclass' else 'discussion',
        'lessonId': 'lesson', 'classroomId': 'room', 'videoRevision': 'revision',
        'context': {'userId': 'student', 'courseId': 'course', 'publication': {'id': 'pub', 'version': 1}},
        'dialogue': deepcopy(dialogue), 'messages': [], 'courses': [], 'preparation': 'ready'}
    if case == 'postclass':
        saved['postclassStage'] = 'remediation'
    persistence.save(saved, 0)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(reader/'student_agent'), str(reader/'student_agent/backend/tests')]),
               PYTHONIOENCODING='utf-8')
    process = subprocess.run([sys.executable, '-c', CHILD, sid, 'yes' if case == '22' else 'no'],
        cwd=reader, env=env, capture_output=True, text=True, encoding='utf-8', timeout=45)
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)['ok']
    restored = persistence.restore(sid)
    if case != '22':
        assert restored['dialogue'] == saved['dialogue']
    else:
        assert restored['dialogue']['points'][0]['status'] == 'mastered'
        assert restored['phase'] == 'done'
