"""Claim a legacy demo course for a real platform teacher (idempotent).

Takes the placeholder-owned course in teacher.mentra_courses, repoints all
ownership fields to a real platform teacher, and registers it with the
platform (public.course + teacher_course_link + enroll code) via the
existing internal registration endpoint. Historical data is never deleted.

Usage:
  platform/.venv/Scripts/python.exe scripts/claim_demo_course.py \
      --course lND264eACd81 --teacher <teacher-uuid-or-email>

Excluded on purpose: placeholder-owned courses stay untouched unless named.
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import psycopg
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def http_json(url: str, payload: dict, headers: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", **headers},
        method="POST")
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=15) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode() or "{}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--course", required=True, help="legacy course id (mentra_courses.id)")
    parser.add_argument("--teacher", required=True, help="real teacher uuid or email")
    args = parser.parse_args()

    env = dotenv_values(ROOT / '.env')
    database_url = env['DATABASE_URL'].replace('+psycopg', '')

    with psycopg.connect(database_url) as connection:
        teacher = connection.execute(
            "SELECT id::text FROM public.user WHERE (id::text=%s OR email=%s) AND role='teacher' AND is_active",
            (args.teacher, args.teacher)).fetchone()
        if not teacher:
            print(f"ERROR: teacher '{args.teacher}' not found or not a teacher")
            return 1
        teacher_id = teacher[0]

        course = connection.execute(
            "SELECT teacher_id, title, payload FROM teacher.mentra_courses WHERE id=%s",
            (args.course,)).fetchone()
        if not course:
            print(f"ERROR: course '{args.course}' not in teacher.mentra_courses")
            return 1
        old_owner, title, payload = course
        payload["teacherId"] = teacher_id
        print(f"claiming '{title}' ({args.course}): {old_owner} -> {teacher_id}")

        connection.execute(
            "UPDATE teacher.mentra_courses SET teacher_id=%s, payload=%s, updated_at="
            "(EXTRACT(EPOCH FROM now())*1000)::bigint WHERE id=%s",
            (teacher_id, json.dumps(payload), args.course))
        # Repoint ownership columns on child tables that carry a teacher_id.
        for table in ("mentra_artifact_jobs", "mentra_course_artifacts"):
            connection.execute(f"UPDATE teacher.{table} SET teacher_id=%s WHERE course_id=%s",
                               (teacher_id, args.course))
        # The graph version table records its author in created_by.
        connection.execute(
            "UPDATE teacher.mentra_course_graph_versions SET created_by=%s WHERE course_id=%s",
            (teacher_id, args.course))
        connection.commit()

    # Register with the platform. Legacy nanoid ids cannot go into
    # public.course (UUID PK), so create a platform UUID and record the
    # mapping in teacher_course_link — the same contract the bridge
    # endpoints use (external_course_id = legacy mentra id).
    import uuid as uuid_mod
    with psycopg.connect(database_url) as connection:
        link = connection.execute(
            "SELECT course_id FROM teacher_course_link WHERE external_course_id=%s",
            (args.course,)).fetchone()
        if link:
            platform_id = link[0]
            print(f"existing platform mapping: {platform_id}")
        else:
            platform_id = str(uuid_mod.uuid4())
            connection.execute(
                "INSERT INTO public.course (id, owner_id, title, enroll_code, description, created_at) "
                "VALUES (%s,%s,%s,%s,%s,now())",
                (platform_id, teacher_id, title,
                 ''.join(__import__('random').choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=8)),
                 payload.get("description")))
            connection.execute(
                "INSERT INTO teacher_course_link (course_id, external_course_id) VALUES (%s,%s)",
                (platform_id, args.course))
            connection.commit()
            print(f"created platform course {platform_id}")

    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            "SELECT enroll_code FROM public.course WHERE id=%s", (platform_id,)).fetchone()
    print(f"DONE. '{title}' claimed by {teacher_id}, enroll code: {row[0]}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
