import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, mkdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';

test('read-only lab requires authentication and exposes only the fixed sample', async (t) => {
  const root = await mkdtemp(path.join(tmpdir(), 'onlyoffice-test-'));
  const token = 'x'.repeat(43);
  const source = Buffer.from('fixed five-page PPTX fixture');
  const sampleSha256 = createHash('sha256').update(source).digest('hex');
  await mkdir(path.join(root, 'audio'));
  await writeFile(path.join(root, 'five-pages.pptx'), source);
  await writeFile(path.join(root, 'sample.json'), JSON.stringify({
    sampleSha256,
    pages: Array.from({ length: 5 }, (_, i) => ({ originalPage: i + 5, cues: [{ audio: `p${i+1}_c1.wav`, text: 'test' }] })),
  }));
  await writeFile(path.join(root, 'audio', 'p1_c1.wav'), Buffer.from('test audio bytes'));
  await writeFile(path.join(root, 'config.json'), JSON.stringify({
    publicOrigin: 'https://example.test', internalOrigin: 'http://agentic-onlyoffice-lab:3212',
    ownerId: 'test-teacher', courseId: 'test-course', jwtSecret: 's'.repeat(48),
    previewToken: token, previewExpiresAt: Date.now() + 3600_000, stateDir: root,
  }));
  const child = spawn(process.execPath, [fileURLToPath(new URL('./server.mjs', import.meta.url))], {
    env: { ...process.env, PORT: '0', ONLYOFFICE_LAB_CONFIG: path.join(root, 'config.json'), ONLYOFFICE_LAB_DATA: root },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  t.after(async () => {
    const done = new Promise((resolve) => child.once('exit', resolve));
    child.kill(); await done;
    await rm(root, { recursive: true, force: true });
  });
  const port = await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('Lab did not start')), 10000);
    child.once('error', reject);
    child.stdout.on('data', (chunk) => {
      const match = /PORT=(\d+)/.exec(String(chunk));
      if (match) { clearTimeout(timeout); resolve(Number(match[1])); }
    });
    child.stderr.on('data', (chunk) => reject(new Error(String(chunk))));
  });
  const base = `http://127.0.0.1:${port}/onlyoffice-test`;
  const headers = { Authorization: `Bearer ${token}` };
  assert.equal((await fetch(base + '/api/config')).status, 401);
  assert.equal((await fetch(base + '/api/audio/p1_c1.wav')).status, 401);
  assert.equal((await fetch(base + '/source.pptx')).status, 403);
  assert.equal((await fetch(base + '/api/config', { headers: { 'x-platform-user-id': 'test-teacher' } })).status, 401);
  const response = await fetch(base + '/api/config', { headers });
  assert.equal(response.status, 200);
  const data = await response.json();
  assert.equal(data.sample.pages.length, 5);
  assert.equal(data.editor.document.permissions.edit, false);
  assert.equal(data.editor.editorConfig.mode, 'view');
  assert.equal(typeof data.editor.token, 'string');
  assert.equal(data.jwtSecret, undefined);
  const documentUrl = new URL(data.editor.document.url);
  const signed = await fetch(`http://127.0.0.1:${port}${documentUrl.pathname}${documentUrl.search}`);
  assert.equal(signed.status, 200);
  assert.deepEqual(Buffer.from(await signed.arrayBuffer()), source);
  assert.equal((await fetch(base + '/api/audio/p1_c1.wav', { headers })).status, 200);
  assert.equal((await fetch(base + '/api/audio/p1_c99.wav', { headers })).status, 404);
  assert.equal((await fetch(base + '/plugin/config.json?nonce=invalid')).status, 403);
  const plugin = await fetch(base + '/plugin/config.json?nonce=' + data.nonce);
  assert.equal(plugin.status, 200);
  const pluginBody = await plugin.json();
  assert.equal(pluginBody.variations[0].isViewer, true);
  const entry = new URL(pluginBody.variations[0].url, pluginBody.baseUrl);
  assert.equal(entry.hash, '');
  const relativeBoot = new URL('./config.json', entry);
  const bootResponse = await fetch(`http://127.0.0.1:${port}${relativeBoot.pathname}?lang=zh-CN`);
  assert.equal(bootResponse.status, 200);
  assert.equal((await bootResponse.json()).guid, pluginBody.guid);
  assert.equal((await fetch(base + '/protocol.mjs')).status, 200);
  assert.equal((await fetch(base + '/api/telemetry', {
    method: 'POST', headers: { ...headers, 'content-type': 'application/json', origin: 'https://attacker.test' },
    body: JSON.stringify({ events: [] }),
  })).status, 403);
});
