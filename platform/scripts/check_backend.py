"""Run migrations and tests only against the isolated app_test database."""
import os
from pathlib import Path
import subprocess
import sys

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
subprocess.run([sys.executable, '-m', 'pytest', 'tests', '-q', '--disable-warnings'], cwd=root / 'backend', env=env, check=True)
