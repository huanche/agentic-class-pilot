"""Part-B acceptance: student trusted entry end to end.

Prerequisites handled by the script itself: publishes the walkthrough course
(synthetic approved artifact + real classroom attach/activate) so students
have formal published content, then exercises the launch flow.

Run with the platform venv python (needs httpx + psycopg):
  platform/.venv/Scripts/python.exe scripts/verify_student_entry.py
"""
import json
import random
import re
import string
import time
import uuid
from pathlib import Path

import httpx
import psycopg

PLATFORM = 'http://127.0.0.1:8080'
STUDENT_AGENT = 'http://127.0.0.1:8000'
TEACHER_AGENT = 'http://127.0.0.1:3200'
COURSE = '667042f9-4152-45d9-a806-26760093c0de'                 # 入口切换验证课程
COURSE_DRAFT = '64ae8a24-4bc4-4a86-91ac-f9db8b89d894'           # 心理健康（未发布）
TEACHER_ID = 'd1d5a41e-4dea-434c-b6e8-e0eee47251af'             # walkthrough teacher
WALKTHROUGH_TEACHER = ('browser-walkthrough-041b17@example.com', 'oZE2zO6ceY8P')
TEACHER_ORIGIN = 'http://localhost:3200'


def load_env() -> dict:
    values = {}
    for line in Path(r'E:\LLM\code_project\ai_education_platform\platform\.env').read_text(encoding='utf-8').splitlines():
        m = re.match(r'^([A-Z_0-9]+)=(.*)$', line.strip())
        if m:
            values[m.group(1)] = m.group(2).strip()
    return values


def random_password() -> str:
    return ''.join(random.choices(string.ascii_letters + string.digits, k=12))


def ensure_published(env: dict) -> None:
    """Publish the walkthrough course formally (idempotent): synthetic approved
    artifact -> course publish -> real classroom attach + activate."""
    with psycopg.connect(env['DATABASE_URL'].replace('+psycopg', '')) as connection:
        existing = connection.execute(
            "SELECT 1 FROM teacher.mentra_course_artifacts WHERE course_id=%s AND status='approved'",
            (COURSE,)).fetchone()
        if not existing:
            now = int(time.time() * 1000)
            artifact = {
                'id': f'p3-publish-{COURSE[:8]}', 'jobId': f'p3-job-{COURSE[:8]}', 'courseId': COURSE,
                'teacherId': TEACHER_ID, 'type': 'lesson-courseware', 'title': '阶段3发布链路课程讲义',
                'content': '阶段 3 学生可信入口验收用已批准产物。', 'scope': {'type': 'course'},
                'status': 'approved', 'citations': [{'materialId': 'p3', 'chunkId': 'p3-1', 'quote': '阶段3'}],
                'createdAt': now, 'updatedAt': now, 'approvedAt': now,
            }
            job = {'id': artifact['jobId'], 'courseId': COURSE, 'teacherId': TEACHER_ID,
                   'scope': {'type': 'course'}, 'artifactType': 'lesson-courseware', 'status': 'approved',
                   'progress': 100, 'message': '', 'createdAt': now, 'updatedAt': now}
            connection.execute(
                "INSERT INTO teacher.mentra_course_artifacts (id,job_id,course_id,teacher_id,artifact_type,status,payload,created_at,updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
                (artifact['id'], artifact['jobId'], COURSE, TEACHER_ID, 'lesson-courseware', 'approved',
                 json.dumps(artifact), now, now))
            connection.execute(
                "INSERT INTO teacher.mentra_artifact_jobs (id,course_id,teacher_id,artifact_type,status,payload,created_at,updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
                (job['id'], COURSE, TEACHER_ID, 'lesson-courseware', 'approved', json.dumps(job), now, now))
        connection.commit()

    with httpx.Client(timeout=30, trust_env=False, base_url=PLATFORM) as platform:
        platform.post('/api/v1/login/access-token',
                      data={'username': WALKTHROUGH_TEACHER[0], 'password': WALKTHROUGH_TEACHER[1]})
        cookie = {'agentedu_session': platform.cookies.get('agentedu_session')}

    with httpx.Client(timeout=60, trust_env=False, base_url=TEACHER_AGENT) as agent:
        course_state = agent.get(f'/api/course-space/{COURSE}', cookies=cookie).json()
        already_published = (course_state.get('course') or {}).get('status') == 'active'
        response = agent.post(f'/api/course-space/{COURSE}/publish', cookies=cookie,
                              headers={'origin': TEACHER_ORIGIN})
        if already_published:
            assert response.status_code in (200, 201, 409), (response.status_code, response.text[:300])
        else:
            assert response.status_code in (200, 201), (response.status_code, response.text[:300])
        classroom = agent.post('/api/classroom', cookies=cookie, headers={'origin': TEACHER_ORIGIN},
                               json={'stage': {'id': f'p3-stage-{COURSE[:8]}', 'name': '阶段3课堂',
                                               'createdAt': 1, 'updatedAt': 1},
                                     'scenes': []}).json()
        classroom_id = classroom['id']
        attached = agent.post(f'/api/course-space/{COURSE}/classrooms/attach', cookies=cookie,
                              headers={'origin': TEACHER_ORIGIN},
                              json={'classroomId': classroom_id, 'title': '阶段3互动课件'}).json()
        artifact_id = attached['artifacts'][0]['id']
        response = agent.patch(f'/api/course-space/{COURSE}/artifacts/{artifact_id}', cookies=cookie,
                               headers={'origin': TEACHER_ORIGIN}, json={'action': 'activate'})
        assert response.status_code == 200, (response.status_code, response.text[:300])
    print(f'PASS course published formally (classroom {classroom_id} activated)', flush=True)


def main() -> None:
    env = load_env()
    suffix = uuid.uuid4().hex[:6]
    # cookie-authenticated writes must carry the frontend origin, like the browser does
    origin = {'origin': env.get('FRONTEND_HOST', 'http://localhost:8080')}
    ensure_published(env)

    with httpx.Client(timeout=30, trust_env=False, base_url=PLATFORM) as platform:
        admin_token = platform.post('/api/v1/login/access-token',
                                    data={'username': env['FIRST_SUPERUSER'], 'password': env['FIRST_SUPERUSER_PASSWORD']}).json()['access_token']
        admin = {'Authorization': f'Bearer {admin_token}'}

        status = platform.get('/api/v1/platform/status', headers=admin).json()
        assert status['studentAgentReady'] is True and status['studentUrl'] == 'http://localhost:8000', status
        print('PASS platform/status studentAgentReady + studentUrl', flush=True)

        password = random_password()
        users = {}
        for name in ('a', 'b'):
            email = f'b-student-{name}-{suffix}@example.com'
            response = platform.post('/api/v1/users/', headers=admin,
                                     json={'email': email, 'password': password, 'role': 'student'})
            assert response.status_code == 200, response.text[:200]
            platform.post('/api/v1/login/access-token', data={'username': email, 'password': password})
            users[name] = {'email': email, 'cookie': {'agentedu_session': platform.cookies.get('agentedu_session')}}

        code = platform.get(f'/api/v1/courses/{COURSE}', headers=admin).json()['enroll_code']
        assert platform.post('/api/v1/enrollments/join', cookies=users['a']['cookie'], headers=origin, json={'code': code}).status_code == 200
        draft_code = platform.get(f'/api/v1/courses/{COURSE_DRAFT}', headers=admin).json()['enroll_code']
        assert platform.post('/api/v1/enrollments/join', cookies=users['b']['cookie'], headers=origin, json={'code': draft_code}).status_code == 200

        # /student states: A published content, B's draft course shows nothing
        published = platform.get(f'/api/v1/courses/{COURSE}/published-content', cookies=users['a']['cookie'], headers=origin).json()
        assert published['knowledgePackage'] is not None
        draft = platform.get(f'/api/v1/courses/{COURSE_DRAFT}/published-content', cookies=users['b']['cookie'], headers=origin).json()
        assert draft['knowledgePackage'] is None
        print('PASS /student published-state distinction', flush=True)

        # gating: B not enrolled in published course; B's own course unpublished; teacher excluded
        assert platform.post(f'/api/v1/courses/{COURSE}/student-workspace', cookies=users['b']['cookie'], headers=origin).status_code == 403
        assert platform.post(f'/api/v1/courses/{COURSE_DRAFT}/student-workspace', cookies=users['b']['cookie'], headers=origin).status_code == 409
        platform.post('/api/v1/login/access-token',
                      data={'username': WALKTHROUGH_TEACHER[0], 'password': WALKTHROUGH_TEACHER[1]})
        teacher_cookie = {'agentedu_session': platform.cookies.get('agentedu_session')}
        assert platform.post(f'/api/v1/courses/{COURSE}/student-workspace', cookies=teacher_cookie, headers=origin).status_code == 403
        print('PASS unenrolled 403 / unpublished 409 / teacher 403', flush=True)

        # enroll B into the published course for the isolation check, then launch both
        assert platform.post('/api/v1/enrollments/join', cookies=users['b']['cookie'], headers=origin, json={'code': code}).status_code == 200
        launch_a = platform.post(f'/api/v1/courses/{COURSE}/student-workspace', cookies=users['a']['cookie'], headers=origin).json()
        launch_b = platform.post(f'/api/v1/courses/{COURSE}/student-workspace', cookies=users['b']['cookie'], headers=origin).json()
        assert launch_a['url'].startswith('http://localhost:8000/app?launch_token='), launch_a['url']
        assert '/classroom-player/' in launch_a['playerUrl'], launch_a
        print(f"PASS launches issued (player ...{launch_a['playerUrl'][-40:]})", flush=True)

    runtime_dir = Path(r'E:\LLM\code_project\ai_education_platform\agent\student_agent\SZU_Student_Agent\runtime\sessions')
    with httpx.Client(timeout=60, trust_env=False, base_url=STUDENT_AGENT) as agent:
        assert agent.get('/api/session/health').status_code == 200
        assert agent.post('/api/session/start', json={'launch_token': launch_a['launchToken'][:-4] + 'beef'}).status_code == 401
        assert agent.post('/api/session/start', json={'launch_token': 'nonsense'}).status_code == 401
        print('PASS tampered/garbage launch tokens rejected (401)', flush=True)

        started = agent.post('/api/session/start',
                             json={'launch_token': launch_a['launchToken'], 'student_id': 'attacker',
                                   'session_id': f'b-{suffix}-a'}).json()
        sid_a = started['session_id']
        record = json.loads((runtime_dir / f'{sid_a}.json').read_text(encoding='utf-8'))
        ctx = record.get('platform', {})
        assert record.get('student_id') != 'attacker' and ctx.get('courseId') == COURSE and ctx.get('publicationVersion') is not None, (record.get('student_id'), ctx)
        print(f"PASS identity authoritative + publication pinned (v{ctx.get('publicationVersion')})", flush=True)

        sid_b = agent.post('/api/session/start',
                           json={'launch_token': launch_b['launchToken'], 'session_id': f'b-{suffix}-b'}).json()['session_id']
        record_b = json.loads((runtime_dir / f'{sid_b}.json').read_text(encoding='utf-8'))
        assert record_b['platform']['userId'] != record['platform']['userId']
        assert record_b['platform']['publicationVersion'] == ctx['publicationVersion']
        print('PASS two parallel student sessions isolated by platform identity', flush=True)

    print('ALL PART-B ENTRY CHECKS PASSED', flush=True)


if __name__ == '__main__':
    main()
