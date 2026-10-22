import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import { createGateway, routeFor } from '../local-gateway.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const python = process.env.LOCAL_TEST_PYTHON ?? path.join(root,
  process.platform === 'win32' ? 'platform/.venv/Scripts/python.exe' : 'platform/.venv/bin/python');
const routes = JSON.parse(execFileSync(python,
  ['-c', 'import json,yaml,sys; print(json.dumps(yaml.safe_load(open(sys.argv[1],encoding="utf-8"))["environments"]["local-extended"]["routes"]))',
    path.join(root, 'contracts/routing.yaml')], { encoding: 'utf8' }));

test('real route contract keeps platform, student and teacher APIs separate', () => {
  for (const [url, port] of [['/api/v1/internal/student/authorize', 8080],
    ['/api/session/health', 8000], ['/api/student/profile', 8000], ['/api/lessons', 8000],
    ['/api/generate', 3200], ['/_next/a.js', 3200],
    ['/vendor/maic-importer/index.js', 3200], ['/login', 8080], ['/app', 8000]]) {
    assert.equal(routeFor(url, routes).port, port, url);
  }
});

test('teacher prefix stripping and redirects preserve signed query strings', () => {
  assert.deepEqual(routeFor('/teacher/api/classroom?id=a%2Bb', routes),
    { port: 3200, path: '/api/classroom?id=a%2Bb' });
  assert.deepEqual(routeFor('/student-agent/app?launch_token=a%2Bb', routes),
    { redirect: '/app?launch_token=a%2Bb', code: 302 });
});

test('proxy forwards POST bodies, cookies and original origin', async () => {
  const upstream = http.createServer(async (req, res) => {
    let body = '';
    for await (const chunk of req) body += chunk;
    res.writeHead(201, { 'content-type': 'application/json',
      'set-cookie': ['one=1; HttpOnly', 'two=2; HttpOnly'] });
    res.end(JSON.stringify({ method: req.method, url: req.url, cookie: req.headers.cookie,
      host: req.headers['x-forwarded-host'], body }));
  });
  await new Promise(resolve => upstream.listen(0, '127.0.0.1', resolve));
  const gateway = createGateway([{ type: 'handle_path', path: '/teacher/*', service: 'teacher' }],
    { teacher: upstream.address().port });
  await new Promise(resolve => gateway.listen(0, '127.0.0.1', resolve));
  try {
    const response = await fetch(`http://127.0.0.1:${gateway.address().port}/teacher/api/save?x=1`,
      { method: 'POST', headers: { cookie: 'session=example' }, body: 'example-body' });
    assert.equal(response.status, 201);
    assert.equal(response.headers.getSetCookie().length, 2);
    assert.deepEqual(await response.json(), { method: 'POST', url: '/api/save?x=1',
      cookie: 'session=example', host: `127.0.0.1:${gateway.address().port}`, body: 'example-body' });
  } finally {
    gateway.closeAllConnections(); upstream.closeAllConnections();
    await Promise.all([new Promise(resolve => gateway.close(resolve)),
      new Promise(resolve => upstream.close(resolve))]);
  }
});
