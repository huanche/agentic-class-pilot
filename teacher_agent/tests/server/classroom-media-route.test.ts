import { afterEach, describe, expect, it, vi } from 'vitest';
import { promises as fs } from 'fs';
import path from 'path';
import { randomUUID } from 'crypto';
import { NextRequest } from 'next/server';

const root = path.resolve(process.cwd(), '.runtime', 'classroom-media-route-tests');
const rooms: string[] = [];

async function routeFor(ext: string) {
  const room = `test-${randomUUID()}`;
  const roomDir = path.join(root, room);
  rooms.push(roomDir);
  await fs.mkdir(path.join(roomDir, ext === '.mp4' ? 'media' : 'audio'), { recursive: true });
  const folder = ext === '.mp4' ? 'media' : 'audio';
  await fs.writeFile(path.join(roomDir, folder, `sample${ext}`), Buffer.from([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]));
  vi.stubEnv('CLASSROOMS_DATA_DIR', root);
  vi.resetModules();
  const { GET } = await import('@/app/api/classroom-media/[classroomId]/[...path]/route');
  const context = { params: Promise.resolve({ classroomId: room, path: [folder, `sample${ext}`] }) };
  const url = `http://teacher.test/api/classroom-media/${room}/${folder}/sample${ext}`;
  return { GET, context, url };
}

afterEach(async () => {
  vi.unstubAllEnvs();
  for (const roomDir of rooms.splice(0)) {
    if (!roomDir.startsWith(root + path.sep)) throw new Error('test media path escaped workspace');
    await fs.rm(roomDir, { recursive: true, force: true });
  }
});

describe('classroom media delivery', () => {
  it('serves video byte ranges for seeking without reading the whole file', async () => {
    const { GET, context, url } = await routeFor('.mp4');
    const response = await GET(new NextRequest(url, { headers: { range: 'bytes=2-5' } }), context);
    expect(response.status).toBe(206);
    expect(response.headers.get('Content-Range')).toBe('bytes 2-5/10');
    expect(response.headers.get('Accept-Ranges')).toBe('bytes');
    expect(Buffer.from(await response.arrayBuffer())).toEqual(Buffer.from([2, 3, 4, 5]));
  });

  it('rejects an unsatisfiable range', async () => {
    const { GET, context, url } = await routeFor('.mp4');
    const response = await GET(new NextRequest(url, { headers: { range: 'bytes=99-' } }), context);
    expect(response.status).toBe(416);
    expect(response.headers.get('Content-Range')).toBe('bytes */10');
  });

  it('revalidates audio even when its URL carries a version', async () => {
    const { GET, context, url } = await routeFor('.wav');
    const versioned = await GET(new NextRequest(`${url}?v=hash-1`), context);
    expect(versioned.headers.get('Cache-Control')).toBe('private, no-cache');
    const unversioned = await GET(new NextRequest(url), context);
    expect(unversioned.headers.get('Cache-Control')).toBe('private, no-cache');
  });

  it('requires revalidation for video and returns 304 for unchanged media', async () => {
    const { GET, context, url } = await routeFor('.mp4');
    const first = await GET(new NextRequest(url), context);
    expect(first.status).toBe(200);
    expect(first.headers.get('Cache-Control')).toBe('private, no-cache');
    const etag = first.headers.get('ETag');
    expect(etag).toBeTruthy();
    const second = await GET(new NextRequest(url, {
      headers: { 'if-none-match': etag! },
    }), context);
    expect(second.status).toBe(304);
    expect(second.headers.get('ETag')).toBe(etag);
  });

  it('sends the whole video if an If-Range validator is stale', async () => {
    const { GET, context, url } = await routeFor('.mp4');
    const response = await GET(new NextRequest(url, {
      headers: { range: 'bytes=2-5', 'if-range': 'W/"stale"' },
    }), context);
    expect(response.status).toBe(200);
    expect(Buffer.from(await response.arrayBuffer())).toEqual(Buffer.from([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]));
  });

  it('allows a student to seek in published clips and rejects draft clips', async () => {
    const room = `test-${randomUUID()}`;
    const roomDir = path.join(root, room);
    rooms.push(roomDir);
    const published = 'a'.repeat(64);
    const draft = 'b'.repeat(64);
    const version = 'c'.repeat(64);
    await fs.mkdir(path.join(roomDir, 'clips'), { recursive: true });
    await fs.mkdir(path.join(roomDir, 'versions'));
    await Promise.all([
      fs.writeFile(path.join(roomDir, 'published.json'), JSON.stringify({ version })),
      fs.writeFile(path.join(roomDir, 'versions', `${version}.json`),
        JSON.stringify({ clips: [{ key: published }] })),
      fs.writeFile(path.join(roomDir, 'clips', `${published}.mp4`), Buffer.from([0, 1, 2, 3])),
      fs.writeFile(path.join(roomDir, 'clips', `${draft}.mp4`), Buffer.from([4, 5, 6, 7])),
    ]);
    vi.stubEnv('CLASSROOM_VIDEOS_DIR', root);
    vi.resetModules();
    const { GET } = await import('@/app/api/classroom-media/[classroomId]/[...path]/route');
    const fetchClip = (key: string) => GET(
      new NextRequest(`http://teacher.test/api/classroom-media/${room}/video/${key}.mp4`, {
        headers: { 'x-platform-role': 'student', range: 'bytes=1-2' },
      }),
      { params: Promise.resolve({ classroomId: room, path: ['video', `${key}.mp4`] }) },
    );
    const allowed = await fetchClip(published);
    expect(allowed.status).toBe(206);
    expect(Buffer.from(await allowed.arrayBuffer())).toEqual(Buffer.from([1, 2]));
    expect((await fetchClip(draft)).status).toBe(404);
  });
});
