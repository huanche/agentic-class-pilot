"""Opt-in real-model HTTP acceptance against a read-only exported published course.

Uses a disposable loopback database and restricted SQL role, never production records.
"""
import json
import os
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from backend import main
from backend.content.context import classroom_materials
from backend.content.knowledge import KnowledgeResult, learning_points
from backend.infrastructure import database, persistence
from backend.session import service as sessions
from backend.teaching import service

pytestmark = pytest.mark.skipif(os.environ.get('STUDENT_RELEASE_COURSE_LIVE') != '1',
                                reason='Opt in to the exported-course real provider acceptance')


def test_published_c_course_extraction_dialogue_and_resume(pg, monkeypatch):
    from dotenv import dotenv_values
    import psycopg
    from psycopg import sql
    source = json.loads(Path(os.environ['STUDENT_RELEASE_COURSE_FIXTURE']).read_text(encoding='utf-8-sig'))
    out = Path(os.environ['STUDENT_RELEASE_COURSE_OUTPUT'])
    out.mkdir(parents=True, exist_ok=False)
    report = {'classroomId': source['classroomId'], 'turns': []}

    def record():
        (out/'acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    assert len(source['classroom']['scenes']) == 22
    assert len(source['videoPlan']['clips']) == 22
    assert all(item['present'] for item in source['clipsPresent'])
    materials = classroom_materials(source['classroom']['scenes'])
    assert len(materials) == 22
    values = {}
    for name in os.environ['STUDENT_RELEASE_MODEL_CONFIG'].split(os.pathsep):
        values.update({k: v for k, v in dotenv_values(name, interpolate=False, encoding='utf-8-sig').items() if v})
    for key, alias in [('STUDENT_AGENT_API_KEY', 'AGENT_LLM_API_KEY'),
                       ('STUDENT_AGENT_BASE_URL', 'AGENT_LLM_BASE_URL'), ('STUDENT_AGENT_MODEL', 'AGENT_LLM_MODEL')]:
        value = values.get(key) or values.get(alias)
        if value:
            monkeypatch.setenv(key, value)
    monkeypatch.setenv('LANGSMITH_TRACING', 'false')
    monkeypatch.setenv('LANGCHAIN_TRACING_V2', 'false')
    monkeypatch.setenv('PLATFORM_TO_STUDENT_KEY', 'isolated-release-forward')
    cached = os.environ.get('STUDENT_RELEASE_EXTRACTED_FIXTURE')
    if cached:
        previous = json.loads(Path(cached).read_text(encoding='utf-8'))
        assert previous['classroomId'] == source['classroomId'] and previous['materials'] == materials
        extracted = KnowledgeResult(points=previous['points'])
        report['extractionReusedFrom'] = str(cached)
    else:
        extracted = learning_points(materials, 'release-course', 'release-lesson')
    report.update(points=extracted.points, coverage={'partial': extracted.partial,
        'accepted': len(extracted.points), 'rejected': extracted.rejected_count,
        'calls': extracted.model_calls}, materials=materials)
    record()
    assert extracted.points and not extracted.partial
    role = 'release_student_' + uuid4().hex
    admin = pg
    with admin() as connection:
        connection.execute(sql.SQL('CREATE ROLE {}').format(sql.Identifier(role)))
        connection.execute(sql.SQL('GRANT USAGE ON SCHEMA student TO {}').format(sql.Identifier(role)))
        connection.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA student TO {}').format(sql.Identifier(role)))
        connection.execute(sql.SQL('GRANT USAGE ON ALL SEQUENCES IN SCHEMA student TO {}').format(sql.Identifier(role)))
        connection.execute(sql.SQL('REVOKE UPDATE,DELETE ON student.lesson_content_versions FROM {}').format(sql.Identifier(role)))

    def restricted():
        connection = admin()
        connection.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(role)))
        return connection

    monkeypatch.setattr(database, '_db', restricted)
    try:
        with restricted() as connection:
            assert connection.execute('SELECT current_user').fetchone()[0] == role
        sid = 'published-course-release-' + uuid4().hex
        seed = {'id': sid, 'phase': 'video', 'lessonId': 'release-lesson',
            'classroomId': source['classroomId'], 'videoRevision': source['publishedVideo']['version'],
            'context': {'userId': 'student', 'courseId': 'release-course', 'publication': {'id': 'release-pub', 'version': 1}},
            'dialogue': service.new_dialogue(extracted.points), 'messages': [], 'courses': [], 'preparation': 'ready'}
        persistence.save(seed, 0)
        client = TestClient(main.app, headers={'X-Platform-Learning-Key': 'isolated-release-forward',
            'X-Platform-Protocol': 'platform-cookie-v1', 'X-Platform-User-Id': 'student',
            'X-Platform-Course-Id': 'release-course'})

        def view():
            response = client.get(f'/api/session/{sid}')
            assert response.status_code == 200, response.text
            return response.json()

        def send(kind, text=None):
            before = view()
            response = client.post(f'/api/session/{sid}/commands', json={'commandId': uuid4().hex,
                'type': kind, 'payload': {'text': text} if text is not None else {},
                'expectedStateVersion': before['stateVersion'], 'contentGeneration': before['contentGeneration']})
            report['turns'].append({'command': kind, 'student': text, 'httpStatus': response.status_code,
                                   'failure': response.json() if response.status_code != 200 else None})
            record()
            assert response.status_code == 200, response.text
            current = response.json()['sessionView']
            report['turns'][-1].update(messages=current['messages'], progress=current.get('learningProgress'))
            record()
            return current

        send('start_discussion')
        send('submit_answer', '为100个数逐个定义变量很繁琐，也不方便用循环处理。数组可以用一个名字和下标统一管理一批同类型的数据。')
        send('submit_answer', '好，然后呢')
        send('submit_answer', '刚才讲过的不用重复，请针对我还没掌握的部分继续。')
        send('submit_answer', '我现在还不确定，请只解释当前卡住的一步。')
        saved = view()
        sessions.sessions.clear()
        restored = view()
        assert restored['messages'] == saved['messages']
        assert restored['stateVersion'] == saved['stateVersion']
        done = send('finish')
        assert done['feedback']['typedTeaching']
        send('continue_after_class')
        send('finish')
        report.update(passed=True, restrictedRole=True, persistedFlowVersion=persistence.restore(sid)['dialogue']['flow_version'])
        record()
    finally:
        monkeypatch.setattr(database, '_db', admin)
        with admin() as connection:
            connection.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
            connection.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
