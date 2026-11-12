"""Opt-in real-model checks at extraction and session-facing teaching interfaces.

Lexical alarms only cover these fixtures; retained outputs need semantic review.
No database writes or replacement model responses.
"""
import json
import os
from pathlib import Path
import re

import pytest

from backend.content import knowledge
from backend.teaching import service

ROOT = Path(__file__).resolve().parents[3]
ARCHIVED_POINT = Path(__file__).parent / 'fixtures/array_design_task.json'
pytestmark = pytest.mark.skipif(os.environ.get('DESIGN_TASK_LIVE') != '1', reason='Opt in to real provider calls')


def record(name, value):
    directory = ROOT / 'student_agent/evidence/design-task-live' / os.environ['DESIGN_TASK_RUN']
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (name + '.json')
    assert not path.exists(), 'Do not overwrite a provider run'
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def archived_point():
    return json.loads(ARCHIVED_POINT.read_text(encoding='utf-8'))


def exposes_solution(text):
    compact = re.sub(r'\s+', '', text)
    return bool(re.search(r'i[<≤]|2\*?i\+1|i\*2\+1|i\+i\+1|i(?:取|依次取|从)0|下标(?:从)?0', compact))


def test_array_example_is_not_a_mandatory_algorithm():
    materials = [{'id': 'arrays', 'title': '循环逐项赋值', 'source': 'published-classroom-scene',
                  'content': '本课学习根据目标序列独立编写for循环给一维数组赋值。示范：定义int a[5]，'
                  '用for(i=0;i<5;i++)执行a[i]=2*i+1，得到1、3、5、7、9。'
                  '循环覆盖所有元素且不越界。示范是一个例子，目标是学会根据要求构造循环，而非背这份代码。'}]
    result = knowledge.learning_points(materials, 'design-verification', 'arrays')
    record('extraction', {'materials': materials, 'points': result.points})
    designs = [p for p in result.points if p['type'] == 'design']
    assert designs
    for point in designs:
        details = point['details']
        assert not exposes_solution(details['capability']), details
        assert not exposes_solution(' '.join(details['constraints'])), details
        assert any('循环' in text or 'for' in text for text in [details['capability'], *details['constraints']]), details
        assert any('越界' in text or '下标' in text or '边界' in text for text in details['successCriteria']), details


def test_explicit_required_formula_is_preserved():
    materials = [{'id': 'specified', 'title': '按指定公式实现', 'source': 'published-classroom-scene',
                  'content': '本课任务明确规定：定义int a[5]，必须使用for循环，按题目指定公式a[i]=2*i+1逐项赋值。'
                  '这里公式是题目给定条件，不考查推导公式。学生需要自己确定合法下标和循环边界，确保得到1、3、5、7、9且不越界。'}]
    result = knowledge.learning_points(materials, 'design-verification', 'specified')
    record('specified-extraction', {'materials': materials, 'points': result.points})
    designs = [p for p in result.points if p['type'] == 'design']
    assert designs
    assert any('2*i+1' in re.sub(r'\s+', '', json.dumps(p['details'], ensure_ascii=False)) for p in designs), designs
    session = {'id': 'specified-verification', 'phase': 'video', 'messages': [],
               'dialogue': service.new_dialogue(designs)}
    session.update(service.start_discussion(session))
    reply = session['messages'][-1]['text']
    record('specified-opening', {'reply': reply})
    assert '2*i+1' in re.sub(r'\s+', '', reply), reply


def test_archived_requirements_do_not_spoil_first_task_and_help_still_works():
    point = archived_point()  # Existing curricula still contain the old, overspecific requirements.
    session = {'id': 'design-verification', 'phase': 'video', 'messages': [],
               'dialogue': service.new_dialogue([point])}
    session.update(service.start_discussion(session))
    opening = session['messages'][-1]['text']
    record('opening', {'point': point, 'reply': opening})
    assert not exposes_solution(opening), opening
    assert 'for' in opening.lower() and '5' in opening, opening
    assert re.search(r'1\D+3\D+5\D+7\D+9', opening), opening
    session.update(service.classroom_turn(session, '我不知道循环的下标该从哪里开始，到哪里结束，请先帮我讲这一步。'))
    help_reply = session['messages'][-1]['text']
    record('help', {'reply': help_reply, 'points': session['dialogue']['points']})
    assert '0' in help_reply and '4' in help_reply, help_reply
    assert session['dialogue']['points'][0]['status'] != 'mastered'
    answer = 'int a[5]; int i; for(i=0;i<5;i++){a[i]=i+i+1;} i依次为0、1、2、3、4，覆盖所有合法下标，没有a[5]，最终是1、3、5、7、9，每项都是奇数。'
    session.update(service.classroom_turn(session, answer))
    record('equivalent-answer', {'answer': answer, 'reply': session['messages'][-1]['text'], 'points': session['dialogue']['points']})
    assert session['dialogue']['points'][0]['status'] == 'mastered'


def test_design_error_exit_resume_and_equivalent_answer_through_commands(pg, monkeypatch):
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from backend import main
    from backend.infrastructure import persistence

    sid = 'design-resume-' + uuid4().hex
    persistence.save({'id': sid, 'phase': 'video', 'lessonId': 'lesson', 'classroomId': 'room',
        'context': {'userId': 'student', 'courseId': 'course', 'publication': {'id': 'pub', 'version': 1}},
        'videoRevision': 'revision', 'messages': [], 'courses': [], 'preparation': 'ready',
        'dialogue': service.new_dialogue([archived_point()])}, 0)
    monkeypatch.setenv('PLATFORM_TO_STUDENT_KEY', 'combined-live-forward')
    client = TestClient(main.app, headers={'X-Platform-Learning-Key': 'combined-live-forward',
        'X-Platform-Protocol': 'platform-cookie-v1', 'X-Platform-User-Id': 'student', 'X-Platform-Course-Id': 'course'})
    trace = []

    def send(kind, text=None):
        view = client.get(f'/api/session/{sid}').json()
        response = client.post(f'/api/session/{sid}/commands', json={'commandId': uuid4().hex,
            'type': kind, 'payload': {'text': text} if text else {},
            'expectedStateVersion': view['stateVersion'], 'contentGeneration': view['contentGeneration']})
        assert response.status_code == 200, response.text
        result = response.json()['sessionView']
        trace.append({'command': kind, 'studentText': text, 'view': result})
        record('combined-command-' + str(len(trace)), trace[-1])
        return result

    opened = send('start_discussion')
    assert not exposes_solution(opened['messages'][-1]['text'])
    wrong = send('submit_answer', 'int a[5]; int i; for(i=0;i<=5;i++){a[i]=2*i+1;} a[5]是合法的最后一项，这样会写入6个奇数。')
    assert wrong['agentStage'] != 'wrapup'
    ended = send('finish')
    assert ended['feedback']['counts']['mastered'] == 0
    requirements = ended['feedback']['points'][0]['requirements']
    resumed = send('continue_after_class')
    # Classroom and after-class tasks have separate IDs; the original question
    # and topic are carried forward, with an explicit resume relation in records.
    assert resumed['currentTaskPublic']['topicId'] == opened['currentTaskPublic']['topicId']
    assert resumed['currentTaskPublic']['question'] == opened['currentTaskPublic']['question']
    response = client.post(f'/api/session/{sid}/learning-records', json={})
    assert response.status_code == 200
    tasks = response.json()['tasks']
    task = next(t for t in tasks if t['taskId'] == resumed['currentTaskPublic']['taskId'])
    assert task['resumesTaskId'] == opened['currentTaskPublic']['taskId']
    assert resumed['messages'][-1]['text'] != opened['messages'][-1]['text']
    assert resumed['feedback']['points'][0]['requirements'] == requirements
    # Repeated entry during active remediation must not call the provider again.
    repeated = send('continue_after_class')
    assert repeated['messages'] == resumed['messages']
    complete = send('postclass_answer', '改为int a[5]; int i; for(i=0;i<5;i++){a[i]=i+i+1;} i只取0、1、2、3、4，合法下标0到4，a[5]越界。最终数组1、3、5、7、9，每项都是奇数，共5项且每个位置恰好赋值一次。')
    assert complete['postclassStage'] == 'completed'
    assert complete['feedback']['counts']['mastered'] == 1
    final = send('continue_after_class')
    assert final['messages'] == complete['messages']
