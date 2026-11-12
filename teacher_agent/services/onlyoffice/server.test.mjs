import { test } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { spawn } from 'node:child_process';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

test('native service delegates ownership, pins original bytes, bounds source capability and can roll back', async () => {
  const dir = await mkdtemp(path.join(tmpdir(), 'native-pptx-test-'));
  const bytes = Buffer.from('verified-test-source');
  const sha = createHash('sha256').update(bytes).digest('hex');
  const secret = 'native-test-secret-'.repeat(4);
  const configFile = path.join(dir, 'config.json');
  const config = { publicOrigin: 'http://127.0.0.1', jwtSecret: secret };
  await writeFile(configFile, JSON.stringify(config));
  await mkdir(path.join(dir, 'classroom_test', 'native'), { recursive: true });
  await writeFile(path.join(dir, 'classroom_test', 'native', 'source.pptx'), bytes);
  let currentSha = sha;
  let upstreamCalls = 0;
  const teacher = http.createServer((req, res) => {
    upstreamCalls++;
    if (req.headers.cookie !== 'agentedu_session=owner' || !req.url.includes('id=classroom_test')) {
      res.writeHead(403);
      res.end('{}');
      return;
    }
    res.setHeader('content-type', 'application/json');
    res.end(
      JSON.stringify({
        classroom: {
          stage: {
            name: 'test',
            nativePptx: {
              version: 1,
              sha256: currentSha,
              pages: { outline_1: 2 },
              compatibility: { converted: 1, unresolved: 0 },
            },
          },
          scenes: [{ id: 'scene_test', outlineId: 'outline_1', type: 'slide', actions: [] }],
        },
      }),
    );
  });
  await new Promise((resolve) => teacher.listen(0, '127.0.0.1', resolve));
  const child = spawn(process.execPath, [fileURLToPath(new URL('./server.mjs', import.meta.url))], {
    env: {
      ...process.env,
      PORT: '0',
      ONLYOFFICE_PLAYER_CONFIG: configFile,
      CLASSROOMS_ROOT: dir,
      TEACHER_INTERNAL_URL: `http://127.0.0.1:${teacher.address().port}`,
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let captured = '';
  try {
    const port = await new Promise((resolve, reject) => {
      const timer = setTimeout(
        () => reject(new Error('native test server startup timeout')),
        10000,
      );
      child.stdout.on('data', (chunk) => {
        captured += chunk;
        const match = /NATIVE_PLAYER_READY (\d+)/.exec(captured);
        if (match) {
          clearTimeout(timer);
          resolve(Number(match[1]));
        }
      });
      child.once('exit', (code) => {
        clearTimeout(timer);
        reject(new Error('native test server exited ' + code));
      });
    });
    const base = `http://127.0.0.1:${port}`;
    const endpoint = base + '/onlyoffice/api/config?classroom=classroom_test&scene=scene_test';
    assert.equal((await fetch(endpoint)).status, 401);
    assert.equal(upstreamCalls, 0);
    assert.equal(
      (
        await fetch(endpoint, {
          headers: { cookie: 'agentedu_session=other', 'x-platform-user-id': 'owner' },
        })
      ).status,
      403,
    );
    const response = await fetch(endpoint, { headers: { cookie: 'agentedu_session=owner' } });
    assert.equal(response.status, 200);
    const data = await response.json();
    assert.equal(data.page, 2);
    assert.equal(data.editor.document.permissions.edit, false);
    const source = new URL(data.editor.document.url);
    const downloaded = await fetch(base + source.pathname + source.search);
    assert.equal(downloaded.status, 200);
    assert.deepEqual(Buffer.from(await downloaded.arrayBuffer()), bytes);
    const repaired = Buffer.from('verified-repaired-source');
    const repairedSha = createHash('sha256').update(repaired).digest('hex');
    await writeFile(path.join(dir, 'classroom_test', 'native', `${repairedSha}.pptx`), repaired);
    currentSha = repairedSha;
    const updated = await (
      await fetch(endpoint, { headers: { cookie: 'agentedu_session=owner' } })
    ).json();
    const repairedUrl = new URL(updated.editor.document.url);
    assert.notEqual(updated.editor.document.key, data.editor.document.key);
    const repairedResponse = await fetch(base + repairedUrl.pathname + repairedUrl.search);
    assert.equal(repairedResponse.status, 200);
    assert.deepEqual(Buffer.from(await repairedResponse.arrayBuffer()), repaired);
    const originalResponse = await fetch(base + source.pathname + source.search);
    assert.equal(originalResponse.status, 200);
    assert.deepEqual(Buffer.from(await originalResponse.arrayBuffer()), bytes);
    await writeFile(path.join(dir, 'classroom_test', 'native', `${repairedSha}.pptx`), 'corrupt');
    assert.equal((await fetch(base + repairedUrl.pathname + repairedUrl.search)).status, 409);
    assert.equal(
      (await fetch(endpoint, { headers: { cookie: 'agentedu_session=owner' } })).status,
      409,
    );
    source.searchParams.set('signature', 'forged');
    assert.equal((await fetch(base + source.pathname + source.search)).status, 403);
    source.searchParams.set('expires', String(Math.floor(Date.now() / 1000) - 1));
    assert.equal((await fetch(base + source.pathname + source.search)).status, 403);
    assert.equal(
      (await fetch(base + '/onlyoffice/plugin/session/' + 'x'.repeat(32) + '/config.json')).status,
      403,
    );
    await writeFile(configFile, JSON.stringify({ ...config, nativeEnabled: false }));
    assert.equal((await (await fetch(base + '/onlyoffice/status')).json()).enabled, false);
    assert.equal(
      (await fetch(endpoint, { headers: { cookie: 'agentedu_session=owner' } })).status,
      503,
    );
  } finally {
    child.kill();
    await new Promise((resolve) => teacher.close(resolve));
    await rm(dir, { recursive: true, force: true });
  }
});
