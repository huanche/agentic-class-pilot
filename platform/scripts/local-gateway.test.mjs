import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {target} from './local-gateway.mjs';

test('PPTX importer and its assets reach the teacher without rewriting the path', () => {
  for (const path of [
    '/vendor/maic-importer/index.js',
    '/vendor/maic-importer/index.js?v=20261020',
    '/vendor/maic-importer/parser/worker.js',
  ]) {
    assert.deepEqual(target(path), {port: 3200, path});
  }
});

test('PPTX routing preserves ownership of the other services', () => {
  for (const path of ['/vendor/other/index.js', '/health', '/api/v1/courses']) {
    assert.deepEqual(target(path), {port: 8080, path});
  }
  for (const path of ['/app/course', '/api/session/current']) {
    assert.deepEqual(target(path), {port: 8000, path});
  }
  assert.deepEqual(target('/teacher/vendor/maic-importer/index.js'), {
    port: 3200, path: '/vendor/maic-importer/index.js',
  });
});

for (const [file, upstream] of [
  ['Caddyfile', 'teacher-agent:3200'],
  ['Caddyfile.local', 'host.docker.internal:3200'],
  ['Caddyfile.dev', 'host.docker.internal:3200'],
]) {
  test(`${file} serves the root importer path from the teacher`, () => {
    const config = readFileSync(new URL('../deployment/' + file, import.meta.url), 'utf8');
    const route = config.match(/handle \/vendor\/maic-importer\/\*\s*\{([^}]+)\}/);
    assert.ok(route, 'A root importer route must precede the platform SPA fallback');
    assert.ok(route[1].includes('reverse_proxy ' + upstream));
    assert.ok(config.indexOf(route[0]) < config.lastIndexOf('handle {'));
  });
}
