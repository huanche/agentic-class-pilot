"""Phase-3 data migration: JSON courses -> teacher.mentra_courses (idempotent).

Migrates ONLY formal courses from the teacher agent's JSON data directory into
the shared database, then (re-)registers them with the platform via the service
endpoint so public.course + teacher_course_link exist. Acceptance/verification
fixtures are explicitly excluded (test data must not enter the formal store).

Selection rule:
  - INCLUDE courses whose id already exists in public.course (platform-registered),
  - INCLUDE courses whose owner is a real platform teacher account whose email
    does not match the disposable verification patterns,
  - EXCLUDE everything else (local-teacher fixtures, phase2-*/browser-walkthrough-*
    verification accounts, unregistered acceptance courses).

Usage: python scripts/migrate_teacher_courses_to_db.py [--dry-run]
"""
import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

from dotenv import dotenv_values
import psycopg

ROOT = Path(__file__).resolve().parents[1]
PLATFORM_ENV = dotenv_values(ROOT / '.env')
JSON_COURSES_DIR = Path(
    r'E:\LLM\code_project\ai_education_platform\agent\teacher_agent'
    r'\SZU-AgentEduPlatform\.runtime\data-3200\course-spaces\courses'
)
VERIFICATION_EMAIL_PATTERNS = (
    re.compile(r'^phase2-'),
    re.compile(r'^browser-walkthrough-'),
    re.compile(r'^nav-student-'),
)


def http_json(url: str, payload: dict, headers: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json', **headers}, method='POST')
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=15) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode() or '{}')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    database_url = PLATFORM_ENV['DATABASE_URL'].replace('+psycopg', '')
    with psycopg.connect(database_url, autocommit=False) as connection:
        platform_courses = {
            row[0] for row in connection.execute('SELECT id::text FROM public.course').fetchall()
        }
        teacher_emails = {
            row[0]: row[1] for row in connection.execute(
                "SELECT id::text, email FROM public.user WHERE role='teacher'").fetchall()
        }

        included, excluded = [], []
        for file in sorted(JSON_COURSES_DIR.glob('*.json')):
            course = json.loads(file.read_text(encoding='utf-8'))
            owner_email = teacher_emails.get(course.get('teacherId'))
            disposable = owner_email and any(
                pattern.match(owner_email) for pattern in VERIFICATION_EMAIL_PATTERNS)
            is_fixture = course.get('teacherId') == 'local-teacher' or disposable
            if course['id'] in platform_courses or (owner_email and not is_fixture and course['id'] in platform_courses):
                included.append(course)
            elif owner_email and not is_fixture:
                # real teacher, not yet platform-registered: include, registration follows
                included.append(course)
            else:
                excluded.append((course['id'], course.get('teacherId'), course.get('title'), 'fixture/verification'))

        print(f"plan: include={len(included)} exclude={len(excluded)}")
        for course_id, teacher_id, title, why in excluded:
            print(f"  EXCLUDE {course_id} | {teacher_id} | {title} | {why}")

        if args.dry_run:
            for course in included:
                print(f"  WOULD MIGRATE {course['id']} | {course['teacherId']} | {course['title']}")
            return 0

        for course in included:
            now = course.get('updatedAt') or 0
            connection.execute(
                """
                INSERT INTO teacher.mentra_courses (id, teacher_id, status, title, payload, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                  teacher_id = EXCLUDED.teacher_id, status = EXCLUDED.status, title = EXCLUDED.title,
                  payload = EXCLUDED.payload, updated_at = EXCLUDED.updated_at
                """,
                (course['id'], course['teacherId'], course.get('status', 'draft'), course.get('title', ''),
                 json.dumps(course), course.get('createdAt', now), now))
        connection.commit()
    print('mentra_courses upsert done')

    service_key = PLATFORM_ENV['TEACHER_SERVICE_KEY']
    for course in included:
        status, body = http_json(
            'http://127.0.0.1:8080/api/v1/internal/teacher/courses',
            {'course_id': course['id'], 'teacher_id': course['teacherId'],
             'title': course.get('title', ''), 'description': course.get('description')},
            {'X-Teacher-Service-Key': service_key})
        print(f"  REGISTER {course['id']} -> {status} {body}")
        if status >= 400:
            return 1
    print('platform registration done')
    return 0


if __name__ == '__main__':
    sys.exit(main())
