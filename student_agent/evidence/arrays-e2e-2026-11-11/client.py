from pathlib import Path
import json
import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).parent
PRIVATE = ROOT / '.runtime/arrays-e2e'
PRIVATE.mkdir(parents=True, exist_ok=True)
CONFIG = dotenv_values(ROOT / 'platform/.env', encoding='utf-8-sig', interpolate=False)
BASE = 'http://localhost:8088'

def save(name, value):
    def redact(item):
        if isinstance(item, list): return [redact(v) for v in item]
        if isinstance(item, dict): return {k: '<REDACTED>' if k.lower() in {'apikey','access_token','password','csrftoken','cookie','authorization','launch_token','enroll_code'} else redact(v) for k,v in item.items()}
        return item
    (OUT / (name + '.json')).write_text(json.dumps(redact(value), ensure_ascii=False, indent=2), encoding='utf-8')

def load(name):
    return json.loads((OUT / (name + '.json')).read_text(encoding='utf-8'))

def login(role='teacher'):
    client = httpx.Client(base_url=BASE, timeout=180, trust_env=False,
                          headers={'Origin':BASE, 'Referer':BASE+'/'})
    if role == 'admin':
        email, password = CONFIG['FIRST_SUPERUSER'], CONFIG['FIRST_SUPERUSER_PASSWORD']
    else:
        account = json.loads((PRIVATE/'accounts.json').read_text(encoding='utf-8'))[role]
        email, password = account['email'], account['password']
    response = client.post('/api/v1/login/access-token', data={'username':email, 'password':password})
    print('login', role, response.status_code, flush=True)
    response.raise_for_status()
    client.headers['Authorization'] = 'Bearer ' + response.json()['access_token']
    metadata = client.get('/api/v1/login/session')
    metadata.raise_for_status()
    client.headers['X-CSRF-Token'] = metadata.json()['csrfToken']
    return client

def call(client, method, url, **kwargs):
    response = client.request(method, url, **kwargs)
    print(method, url, response.status_code, flush=True)
    if not response.is_success:
        print(response.text[:1500], flush=True)
    response.raise_for_status()
    return response.json()
