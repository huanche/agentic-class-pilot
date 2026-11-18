"""真实 PostgreSQL 验证名单写入；仅使用显式指定的测试服务器和新建临时库。"""
import importlib.util
import os
from pathlib import Path
import sys
import uuid

import psycopg
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlmodel import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'platform/backend'))
from app.services.course_roster import RosterEntry, load_roster, save_roster

COURSE, OTHER_COURSE, USER, OTHER_USER, OUTSIDER = [uuid.UUID(int=n) for n in range(1, 6)]


@pytest.fixture
def session(monkeypatch):
    url = os.environ.get('ROSTER_TEST_DATABASE_URL')
    if not url:
        pytest.skip('set ROSTER_TEST_DATABASE_URL to an isolated test PostgreSQL server')
    database = 'test_course_roster_' + uuid.uuid4().hex
    admin = psycopg.connect(url, autocommit=True)
    admin.execute(psycopg.sql.SQL('CREATE DATABASE {}').format(psycopg.sql.Identifier(database)))
    conninfo = psycopg.conninfo.conninfo_to_dict(url)
    conninfo['dbname'] = database
    engine = create_engine('postgresql+psycopg://', creator=lambda: psycopg.connect(**conninfo))
    try:
        with Session(engine) as db:
            db.execute(text('CREATE TABLE course (id UUID PRIMARY KEY)'))
            db.execute(text('CREATE TABLE "user" (id UUID PRIMARY KEY, full_name TEXT)'))
            db.execute(text('CREATE TABLE enrollment (course_id UUID, student_id UUID)'))
            db.execute(text('INSERT INTO course VALUES (:a), (:b)'), {'a': COURSE, 'b': OTHER_COURSE})
            for student in [USER, OTHER_USER, OUTSIDER]:
                db.execute(text('INSERT INTO "user" VALUES (:id, :name)'), {'id': student, 'name': 'registered-name'})
            for student in [USER, OTHER_USER]:
                db.execute(text('INSERT INTO enrollment VALUES (:course, :student)'), {'course': COURSE, 'student': student})
            spec = importlib.util.spec_from_file_location('roster_migration', ROOT / 'platform/backend/app/alembic/versions/roster15_course_student_profiles.py')
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            monkeypatch.setattr(migration.op, 'execute', lambda sql: db.execute(text(sql)))
            migration.upgrade()
            db.commit()
            yield db
    finally:
        engine.dispose()
        admin.execute(psycopg.sql.SQL('DROP DATABASE {} WITH (FORCE)').format(psycopg.sql.Identifier(database)))
        admin.close()


def entry(number='20240001', student=USER, **values):
    return RosterEntry(studentNumber=number, name='真实姓名', studentId=student, **values)


def previous(db, course=COURSE):
    return [RosterEntry.model_validate(row) for row in load_roster(db, course)]


def test_migration_import_update_pending_and_course_isolation(session):
    save_roster(session, COURSE, [entry(major='通信工程', gender='女'), entry('20240002', None)], [])
    assert len(load_roster(session, COURSE)) == 2
    assert load_roster(session, OTHER_COURSE) == []
    save_roster(session, COURSE, [entry(grade='2024级')], previous(session))
    assert len(load_roster(session, COURSE)) == 2  # 未上传的行不删除
    assert load_roster(session, COURSE)[0]['grade'] == '2024级'
    assert session.execute(text('SELECT count(*) FROM enrollment')).scalar() == 2
    assert set(session.execute(text('SELECT full_name FROM "user"')).scalars()) == {'registered-name'}


@pytest.mark.parametrize('entries', [
    [entry(student=OUTSIDER)],
    [entry(), entry('20240002')],
    [entry(), entry(student=OTHER_USER)],
])
def test_rejects_outsider_duplicate_account_and_duplicate_number(session, entries):
    with pytest.raises(HTTPException) as error:
        save_roster(session, COURSE, entries, [])
    assert error.value.status_code == 422
    session.rollback()
    assert load_roster(session, COURSE) == []


def test_stale_preview_does_not_overwrite_and_swap_is_atomic(session):
    save_roster(session, COURSE, [entry(), entry('20240002', OTHER_USER)], [])
    with pytest.raises(HTTPException) as error:
        save_roster(session, COURSE, [entry(grade='stale')], [])
    assert error.value.status_code == 409
    session.rollback()
    save_roster(session, COURSE, [entry(student=OTHER_USER), entry('20240002')], previous(session))
    assert [row['studentId'] for row in load_roster(session, COURSE)] == [str(OTHER_USER), str(USER)]
    with pytest.raises(HTTPException) as conflict:
        save_roster(session, COURSE, [entry('20240003')], previous(session))
    assert conflict.value.status_code == 422
    session.rollback()
    assert len(load_roster(session, COURSE)) == 2
