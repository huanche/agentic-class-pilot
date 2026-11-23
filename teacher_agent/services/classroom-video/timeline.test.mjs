import test from 'node:test';
import assert from 'node:assert/strict';
import { promises as fs } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { zipSync, strToU8 } from 'fflate';
import { unpackTimelineProject } from './timeline.mjs';

test('unpacks a self-contained animation project', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'timeline-test-'));
  try {
    const bytes = zipSync({
      'index.html': strToU8('<html></html>'),
      'assets/a.png': new Uint8Array([1]),
    });
    await unpackTimelineProject(Buffer.from(bytes).toString('base64'), root);
    assert.equal(await fs.readFile(path.join(root, 'index.html'), 'utf8'), '<html></html>');
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});
test('refuses path traversal and projects without an entry page', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'timeline-test-'));
  try {
    const archive = (files) => Buffer.from(zipSync(files)).toString('base64');
    await assert.rejects(
      unpackTimelineProject(
        archive({ 'index.html': strToU8('ok'), '../escape': strToU8('bad') }),
        root,
      ),
      /路径/,
    );
    await assert.rejects(
      unpackTimelineProject(archive({ 'a.txt': strToU8('bad') }), root),
      /index.html/,
    );
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});
