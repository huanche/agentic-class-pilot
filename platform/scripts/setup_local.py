"""Prepare isolated local configuration without displaying secrets."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
if (root / '.env').exists():
    raise SystemExit('Configuration already exists; refusing to overwrite.')
password = secrets.token_hex(24)
secret = secrets.token_hex(32)
teacher_password = secrets.token_hex(24)
admin_password = secrets.token_urlsafe(18) + 'Aa1!'
service_key = secrets.token_hex(32)
env = f'''PROJECT_NAME=AI Education Platform
SECRET_KEY={secret}
DATABASE_URL=postgresql://platform:{password}@127.0.0.1:55432/education
FIRST_SUPERUSER=admin@example.com
FIRST_SUPERUSER_PASSWORD={admin_password}
FRONTEND_HOST=http://localhost:8080
FASTAPI_ENV=development
ENVIRONMENT=development
SMTP_HOST=127.0.0.1
SMTP_PORT=51025
SMTP_TLS=false
EMAILS_FROM_EMAIL=noreply@example.com
POSTGRES_PASSWORD={password}
TEACHER_DB_PASSWORD={teacher_password}
TEACHER_SERVICE_KEY={service_key}
TEACHER_URL=http://127.0.0.1:3200
MINIO_ROOT_USER=agentedu
COURSE_OBJECT_STORAGE_MODE=minio
COURSE_OBJECT_STORAGE_ENDPOINT=http://127.0.0.1:59000
COURSE_OBJECT_STORAGE_REGION=us-east-1
COURSE_OBJECT_STORAGE_BUCKET=agentedu-course-files
COURSE_OBJECT_STORAGE_ACCESS_KEY=agentedu
COURSE_OBJECT_STORAGE_FORCE_PATH_STYLE=true
PLATFORM_URL=http://127.0.0.1:8080
EMBEDDED_AGENTS_ENABLED=false
LLM_API_KEY=local-disabled-placeholder
'''
(root / '.env').write_text(env, encoding='utf-8')
(root / 'LOCAL-ACCESS.txt').write_text(f'Platform: http://localhost:8080\nEmail: admin@example.com\nPassword: {admin_password}\nLocal mail inbox: http://localhost:58025\n', encoding='utf-8')
init = root / 'local-db-init'
init.mkdir(exist_ok=True)
(init / '01-roles.sql').write_text(f"CREATE ROLE teacher LOGIN PASSWORD '{teacher_password}';\nCREATE SCHEMA teacher AUTHORIZATION teacher;\nREVOKE CREATE ON SCHEMA public FROM PUBLIC;\nALTER ROLE teacher SET search_path=teacher;\nCREATE DATABASE app_test;\n", encoding='utf-8')
print('Local configuration prepared (credentials in LOCAL-ACCESS.txt).')
