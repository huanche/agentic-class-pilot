"""Phase-2 identity integration verification: platform-authoritative teacher identity.

Real flow against the running platform (:8080) and teacher agent (:3200):
provision a teacher and a student via the platform admin API (the email signup
round-trip is covered by the platform's own test suite), log in for real
``agentedu_session`` cookies, then verify 401/403/200 gates, query/body teacherId
spoofing resistance, service delegation idempotency, and the expected
registration degradation (JSON storage mode; full round-trip lands in phase 3).
"""
import random
import re
import string
import time
import uuid
from pathlib import Path

import httpx

PLATFORM = 'http://127.0.0.1:8080'
TEACHER = 'http://127.0.0.1:3200'
TEACHER_ORIGIN = 'http://localhost:3200'


def load_platform_env() -> dict[str, str]:
    env_file = Path(r'E:\LLM\code_project\ai_education_platform\platform\.env')
    values: dict[str, str] = {}
    for line in env_file.read_text(encoding='utf-8').splitlines():
        match = re.match(r'^([A-Z_0-9]+)=(.*)$', line.strip())
        if match:
            values[match.group(1)] = match.group(2).strip()
    return values


def random_password() -> str:
    return ''.join(random.choices(string.ascii_letters + string.digits, k=12))


def admin_provision_and_login(platform: httpx.Client, platform_env: dict[str, str],
                              email: str, password: str, role: str) -> dict:
    token_response = platform.post('/api/v1/login/access-token',
                                   data={'username': platform_env['FIRST_SUPERUSER'],
                                         'password': platform_env['FIRST_SUPERUSER_PASSWORD']})
    assert token_response.status_code == 200, token_response.text[:300]
    admin_headers = {'Authorization': f"Bearer {token_response.json()['access_token']}"}
    response = platform.post('/api/v1/users/', headers=admin_headers,
                             json={'email': email, 'password': password, 'role': role})
    assert response.status_code == 200, (response.status_code, response.text[:300])
    response = platform.post('/api/v1/login/access-token',
                             data={'username': email, 'password': password})
    assert response.status_code == 200, (response.status_code, response.text[:300])
    me = platform.get('/api/v1/users/me')
    assert me.status_code == 200, me.text[:300]
    return me.json()


def wait_ready(url: str, path: str, client: httpx.Client) -> None:
    for _ in range(60):
        try:
            if client.get(f'{url}{path}').status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise SystemExit(f'{url}{path} not ready')


def main() -> None:
    platform_env = load_platform_env()
    service_key = platform_env['TEACHER_SERVICE_KEY']
    suffix = uuid.uuid4().hex[:8]
    teacher_email = f'phase2-teacher-{suffix}@example.com'
    student_email = f'phase2-student-{suffix}@example.com'
    password = random_password()

    with httpx.Client(timeout=60, trust_env=False) as raw, \
            httpx.Client(timeout=60, trust_env=False, base_url=PLATFORM) as platform:
        wait_ready(PLATFORM, '/docs', raw)
        wait_ready(TEACHER, '/api/health', raw)
        print('PASS both services healthy', flush=True)

        teacher = admin_provision_and_login(platform, platform_env, teacher_email, password, 'teacher')
        # Capture before the student login overwrites the shared cookie jar.
        teacher_cookie = {'agentedu_session': platform.cookies.get('agentedu_session')}
        assert teacher_cookie['agentedu_session'], 'login did not set agentedu_session cookie'
        admin_provision_and_login(platform, platform_env, student_email, password, 'student')
        print(f"PASS accounts teacher={teacher['id']} student={student_email}", flush=True)

        with httpx.Client(timeout=60, trust_env=False, base_url=TEACHER) as agent:
            response = agent.get('/api/course-space')
            assert response.status_code == 401, response.text[:200]
            response = agent.get('/course-space', follow_redirects=False)
            assert response.status_code == 307 and response.headers['location'] == 'http://localhost:8080/login', \
                (response.status_code, response.headers.get('location'))
            print('PASS anonymous: API 401, page redirect to platform login', flush=True)

            response = agent.get('/api/course-space', cookies=dict(platform.cookies))
            assert response.status_code == 403, (response.status_code, response.text[:200])
            print('PASS student role denied (403) on teacher service', flush=True)

            response = agent.get('/api/course-space', cookies=teacher_cookie)
            assert response.status_code == 200 and response.json()['courses'] == [], response.text[:200]
            print('PASS teacher session lists own (empty) courses', flush=True)

            response = agent.post('/api/course-space', cookies=teacher_cookie,
                                  json={'title': 'Phase 2 identity course'},
                                  headers={'origin': TEACHER_ORIGIN})
            assert response.status_code == 502, (response.status_code, response.text[:300])
            listed = agent.get('/api/course-space', cookies=teacher_cookie).json()['courses']
            assert len(listed) == 1, listed
            created = listed[0]
            uuid.UUID(created['id'])
            assert created['teacherId'] == teacher['id'], created
            print(f"PASS course created with UUID {created['id']}; registration degraded 502 as documented", flush=True)

            spoofed = agent.get('/api/course-space', cookies=teacher_cookie,
                                params={'teacherId': 'local-teacher'}).json()['courses']
            assert [c['id'] for c in spoofed] == [created['id']], spoofed
            print('PASS query teacherId spoof ignored; platform identity authoritative', flush=True)

            platform_course_id = str(uuid.uuid4())
            headers = {'X-Platform-Service-Key': service_key, 'X-Platform-Subject': teacher['id']}
            response = agent.post('/api/course-space', headers=headers,
                                  json={'id': platform_course_id, 'title': 'Platform provisioned workspace'})
            assert response.status_code == 201 and response.json()['course']['id'] == platform_course_id, response.text[:300]
            repeat = agent.post('/api/course-space', headers=headers,
                                json={'id': platform_course_id, 'title': 'Platform provisioned workspace'})
            assert repeat.status_code == 200 and repeat.json()['course']['id'] == platform_course_id, repeat.text[:300]
            listed = agent.get('/api/course-space', cookies=teacher_cookie).json()['courses']
            assert len(listed) == 2, [c['id'] for c in listed]
            print('PASS delegated service call: exact UUID honored, idempotent, no duplicate', flush=True)

            response = agent.post('/api/course-space',
                                  headers={'X-Platform-Service-Key': 'wrong-key',
                                           'X-Platform-Subject': teacher['id']},
                                  json={'id': str(uuid.uuid4()), 'title': 'should fail'})
            # A wrong service key demotes the caller to anonymous (no cookie -> 401);
            # the authorize endpoint itself rejects the bad key with 403 (unit-tested).
            assert response.status_code == 401, (response.status_code, response.text[:200])
            print('PASS wrong service key treated as anonymous (401)', flush=True)

            response = agent.get(f"/api/course-space/{uuid.uuid4()}", cookies=teacher_cookie)
            assert response.status_code == 404, (response.status_code, response.text[:200])
            print('PASS unknown course scoped path denied (404; ownership 403 lands with phase 3 shared DB)', flush=True)

    print('ALL PHASE-2 IDENTITY CHECKS PASSED', flush=True)


if __name__ == '__main__':
    main()
