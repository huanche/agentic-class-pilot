"""Opt-in real-provider regression; retained replies also require human review."""
from copy import deepcopy
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from backend import main
from backend.infrastructure import persistence
from backend.teaching import service

pytestmark = pytest.mark.skipif(os.environ.get('COMPOUND_HELP_LIVE') != '1', reason='Opt in to real provider')
ROOT = Path(__file__).resolve().parents[3]


def record(name, data):
    folder = ROOT / 'student_agent/evidence/compound-help-fix' / os.environ['COMPOUND_HELP_RUN']
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (name + '.json')
    assert not path.exists()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def command_session(pg, monkeypatch, dialogue, messages):
    sid = 'compound-help-' + uuid4().hex
    monkeypatch.setenv('PLATFORM_TO_STUDENT_KEY', 'compound-help-forward')
    persistence.save({'id': sid, 'phase': 'discussion', 'lessonId': 'lesson', 'classroomId': 'room',
        'context': {'userId': 'student', 'courseId': 'course', 'publication': {'id': 'pub', 'version': 1}},
        'videoRevision': 'revision', 'messages': messages, 'courses': [], 'preparation': 'ready', 'dialogue': dialogue}, 0)
    client = TestClient(main.app, headers={'X-Platform-Learning-Key': 'compound-help-forward',
        'X-Platform-Protocol': 'platform-cookie-v1', 'X-Platform-User-Id': 'student', 'X-Platform-Course-Id': 'course'})

    def send(text, label):
        view = client.get(f'/api/session/{sid}').json()
        response = client.post(f'/api/session/{sid}/commands', json={'commandId': uuid4().hex,
            'type': 'submit_answer', 'payload': {'text': text}, 'expectedStateVersion': view['stateVersion'],
            'contentGeneration': view['contentGeneration']})
        assert response.status_code == 200, response.text
        after = persistence.restore(sid)['dialogue']
        record(label, {'student': text, 'response': response.json(), 'dialogue': after})
        return after
    return send


@pytest.mark.parametrize('case', ['incomplete', 'last-incomplete', 'complete', 'prior-evidence'])
def test_compound_requires_cumulative_evidence_for_both_facts(pg, monkeypatch, case):
    point = json.loads((Path(__file__).parent / 'fixtures/chain_queue_compound.json').read_text(encoding='utf-8'))
    state = service.new_dialogue([point])
    focus = state['points'][0]
    question = 'front和rear分别指向什么？链队列为什么没有固定数组的队满问题？'
    focus.update(task_question=question, latest_question=question)
    answer = 'front应该指向队头结点，rear指向队尾结点。没有队满是因为结点动态分配，不像数组有固定下标末端，只要内存还能分配就能继续入队。'
    if case == 'complete':
        answer += '入队时把新结点链接在原rear结点之后，再更新rear为新结点。'
    if case == 'prior-evidence':
        focus['assessment_history'] = [{'stage': 'recall', 'round': 1, 'result': 'partial',
            'evidence': '已说明插入位置', 'studentText': '入队把新结点链接在原rear结点之后，再更新rear。', 'question': '怎样入队？'}]
    if case == 'last-incomplete':
        for item in focus['requirements']:
            if item['id'] != 'understandingPoints:2':
                item.update(status='demonstrated', evidence='受控前置已确认', studentText='受控对照', gap='')
    send = command_session(pg, monkeypatch, state, [{'role': 'assistant', 'text': question, 'phase': 'recall'}])
    after = send(answer, case)
    item = after['points'][0]['requirements'][1]
    assert (item['status'] == 'demonstrated') == (case in {'complete', 'prior-evidence'}), item
    if case in {'incomplete', 'last-incomplete'}:
        assert item['status'] == 'unconfirmed'
        assert after['points'][0]['status'] != 'mastered'


def test_stalled_design_does_not_replay_whole_program(pg, monkeypatch):
    archive = Path(__file__).parent / 'fixtures/stalled_array_design.json'
    saved = json.loads(archive.read_text(encoding='utf-8'))
    state = deepcopy(saved['dialogue'] if 'dialogue' in saved else saved)
    messages = [{'role': 'assistant', 'text': entry['text'], 'phase': 'recall'}
                for entry in state['points'][0]['question_history']]
    send = command_session(pg, monkeypatch, state, messages)
    for index in range(2):
        after = send('不知道', f'stalled-{index}')
        text = after['reply']
        assert 'int main' not in text and '#include' not in text, text
        assert after['points'][0]['status'] != 'mastered'
    assert after['points'][0]['recall_attempts'] == 5
    assert after['points'][0]['reinforce_attempts'] == 0
    assert after['stage'] == 'reinforce'


@pytest.mark.parametrize('complete', [False, True])
def test_other_compound_fact_is_not_confirmed_from_one_half(pg, monkeypatch, complete):
    text = '队列只能在队尾插入、在队头删除。'
    point = {'id': 'queue', 'type': 'memory', 'title': '队列的操作位置',
        'details': {'statement': text, 'requiredElements': [text]}, 'content': text, 'description': text}
    state = service.new_dialogue([point])
    question = '队列从哪里插入？'
    state['points'][0].update(task_question=question, latest_question=question)
    send = command_session(pg, monkeypatch, state, [{'role': 'assistant', 'text': question, 'phase': 'recall'}])
    after = send('队尾插入。' + ('队头删除。' if complete else ''), f'queue-{complete}')
    item = after['points'][0]['requirements'][0]
    assert (item['status'] == 'demonstrated') == complete
    assert (after['points'][0]['status'] == 'mastered') == complete
