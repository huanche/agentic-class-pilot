"""Run pytest against the isolated app_test database with the full local .env,
scoped to the given test paths. Usage: python scripts/pytest_route.py tests/api/routes/test_x.py [-k name]

Same environment contract as check_backend.py (which always runs the whole
suite); this variant accepts pytest arguments for focused iteration.
"""
import os
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
config = dotenv_values(root / '.env')
env = dict(os.environ)
env.update({key: value for key, value in config.items() if value is not None})
env['DATABASE_URL'] = config['DATABASE_URL'].rsplit('/', 1)[0] + '/app_test'
env['TEST_DATABASE_URL'] = env['DATABASE_URL']
env['EMBEDDED_AGENTS_ENABLED'] = 'true'
env['LLM_API_KEY'] = 'local-test-placeholder'
subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=root / 'backend', env=env, check=True)
subprocess.run([sys.executable, '-m', 'pytest', *sys.argv[1:]], cwd=root / 'backend', env=env, check=False)
