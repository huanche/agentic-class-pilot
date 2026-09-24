"""Back up verified destination and grant its isolated teacher service access.

Does not rewrite course owners, session counters, or any imported payload.
"""
from pathlib import Path
import subprocess
import psycopg
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
assert (root / 'backups/teacher-copy-verification.json').exists()
backup = subprocess.check_output(['docker','exec','agentedu-final-database-1','pg_dump','-U','platform','-d','education','--schema=teacher','--no-owner','--no-acl'])
(root / 'backups/teacher-destination-before-integration.sql').write_bytes(backup)
config = dotenv_values(root / '.env')
with psycopg.connect(config['DATABASE_URL']) as db:
    db.execute('GRANT USAGE ON SCHEMA teacher TO teacher')
    db.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA teacher TO teacher')
    db.execute('GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA teacher TO teacher')
    db.execute('ALTER DEFAULT PRIVILEGES FOR ROLE teacher IN SCHEMA teacher GRANT SELECT ON TABLES TO platform')
print('Destination backed up; isolated teacher role granted access; imported rows unchanged.')
