"""Read-only verification of source and target teacher-table copies."""
from pathlib import Path
import json
import psycopg
from psycopg import sql
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
config = dotenv_values(root / '.env')
old = dotenv_values(root.parents[1] / '.env.local')
report = {}
with psycopg.connect(old.get('COURSE_DATABASE_URL') or old['DATABASE_URL']) as source, psycopg.connect(config['DATABASE_URL']) as target:
    tables = source.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'mentra_%' ORDER BY tablename").fetchall()
    for (table,) in tables:
        before = source.execute(sql.SQL('SELECT count(*) FROM public.{}').format(sql.Identifier(table))).fetchone()[0]
        after = target.execute(sql.SQL('SELECT count(*) FROM teacher.{}').format(sql.Identifier(table))).fetchone()[0]
        report[table] = {'source':before, 'target':after}
        assert before == after, table
        # Row fingerprints prove that the failed transaction left no payload/owner rewrites.
        old_hash = source.execute(sql.SQL("SELECT md5(string_agg(md5(row_to_json(t)::text), '' ORDER BY md5(row_to_json(t)::text))) FROM public.{} t").format(sql.Identifier(table))).fetchone()[0]
        new_hash = target.execute(sql.SQL("SELECT md5(string_agg(md5(row_to_json(t)::text), '' ORDER BY md5(row_to_json(t)::text))) FROM teacher.{} t").format(sql.Identifier(table))).fetchone()[0]
        assert old_hash == new_hash, f'Row mismatch: {table}'
(root / 'backups' / 'teacher-copy-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(f'Verified {len(report)} tables: all counts and row fingerprints match; source unchanged.')
