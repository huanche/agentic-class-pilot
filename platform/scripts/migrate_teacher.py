"""Backup and copy teacher tables to the isolated database; never mutate source."""
from pathlib import Path
import json
import subprocess
import sys

import psycopg
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
config = dotenv_values(root / '.env')
backup = root / 'backups'
backup.mkdir(exist_ok=True)
if (backup / 'teacher-migration.json').exists():
    raise SystemExit('Teacher migration already recorded; refusing duplicate import.')

source_container = 'ai_education_platform_demo-db-1'
target_container = 'agentedu-final-database-1'
source_user = subprocess.check_output(['docker','exec',source_container,'printenv','POSTGRES_USER'], text=True).strip()
raw = subprocess.check_output(['docker','exec',source_container,'pg_dump','-U',source_user,'-d','teacher_agent_db','--no-owner','--no-acl','--table=public.mentra_*'])
(backup / 'teacher-original.sql').write_bytes(raw)
sql = raw.replace(b'public.', b'teacher.')
if '--resume-import' not in sys.argv:
    subprocess.run(['docker','exec','-i',target_container,'psql','-U','platform','-d','education','-v','ON_ERROR_STOP=1'], input=sql, check=True, stdout=subprocess.DEVNULL)
with psycopg.connect(config['DATABASE_URL']) as db:
    admin = db.execute('SELECT id FROM "user" WHERE email=%s',(config['FIRST_SUPERUSER'],)).fetchone()[0]
    tables = db.execute("SELECT tablename FROM pg_tables WHERE schemaname='teacher' ORDER BY tablename").fetchall()
    report = {'source': 'teacher_agent_db (unchanged)', 'destination': 'education.teacher', 'tables': {}, 'previous_owners': []}
    for (table,) in tables:
        report['tables'][table] = db.execute(psycopg.sql.SQL('SELECT count(*) FROM teacher.{}').format(psycopg.sql.Identifier(table))).fetchone()[0]
        columns = {r[0] for r in db.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='teacher' AND table_name=%s",(table,))}
        if 'teacher_id' in columns:
            report['previous_owners'].extend(str(r[0]) for r in db.execute(psycopg.sql.SQL('SELECT DISTINCT teacher_id FROM teacher.{}').format(psycopg.sql.Identifier(table))))
            db.execute(psycopg.sql.SQL('UPDATE teacher.{} SET teacher_id=%s').format(psycopg.sql.Identifier(table)),(str(admin),))
            if 'payload' in columns:
                db.execute(psycopg.sql.SQL("UPDATE teacher.{} SET payload=jsonb_set(payload, '{{teacherId}}', to_jsonb(%s::text))").format(psycopg.sql.Identifier(table)),(str(admin),))
        if 'owner_id' in columns and table == 'mentra_teacher_agent_sessions':
            db.execute(psycopg.sql.SQL('UPDATE teacher.{} SET owner_id=%s').format(psycopg.sql.Identifier(table)),(str(admin),))
        db.execute(psycopg.sql.SQL('ALTER TABLE teacher.{} OWNER TO teacher').format(psycopg.sql.Identifier(table)))
    report['previous_owners'] = sorted(set(report['previous_owners']))
    db.execute('GRANT USAGE ON SCHEMA teacher TO platform')
    db.execute('GRANT SELECT ON ALL TABLES IN SCHEMA teacher TO platform')
(backup / 'teacher-migration.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'tables':len(report['tables']), 'rows':sum(report['tables'].values()), 'backup':str(backup)},ensure_ascii=False))
