import { promises as fs, createReadStream } from 'fs';
import { Readable } from 'stream';
import path from 'path';
import { NextRequest, NextResponse } from 'next/server';
import { CLASSROOMS_DIR, isValidClassroomId } from '@/lib/server/classroom-storage';
import { createLogger } from '@/lib/logger';
import { CLASSROOM_VIDEOS_DIR, readVideoPlan, videoPointer } from '@/lib/server/classroom-video';
import { parseByteRange } from '@/lib/server/http-range';

const log = createLogger('ClassroomMedia');

const MIME_TYPES: Record<string, string> = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.gif': 'image/gif',
  '.mp4': 'video/mp4',
  '.webm': 'video/webm',
  '.mp3': 'audio/mpeg',
  '.wav': 'audio/wav',
  '.ogg': 'audio/ogg',
  '.aac': 'audio/aac',
};

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ classroomId: string; path: string[] }> },
) {
  const { classroomId, path: pathSegments } = await params;

  // Validate classroomId
  if (!isValidClassroomId(classroomId)) {
    return NextResponse.json({ error: 'Invalid classroom ID' }, { status: 400 });
  }

  // Validate path segments — no traversal
  const joined = pathSegments.join('/');
  if (joined.includes('..') || pathSegments.some((s) => s.includes('\0'))) {
    return NextResponse.json({ error: 'Invalid path' }, { status: 400 });
  }

  // Generated MP4 files use a separate store and a published version pointer.
  const subDir = pathSegments[0];
  if (subDir !== 'media' && subDir !== 'audio' && subDir !== 'video') {
    return NextResponse.json({ error: 'Invalid path' }, { status: 404 });
  }

  const isGeneratedVideo = subDir === 'video';
  if (isGeneratedVideo && (pathSegments.length !== 2 || !/^[a-f0-9]{64}\.mp4$/.test(pathSegments[1])))
    return NextResponse.json({ error: 'Not found' }, { status: 404 });
  if (isGeneratedVideo && req.headers.get('x-platform-role') === 'student') {
    const pointer = await videoPointer(classroomId, 'published');
    const plan = pointer && await readVideoPlan(classroomId, pointer.version);
    if (!plan || !plan.clips.some((c) => `${c.key}.mp4` === pathSegments[1]))
      return NextResponse.json({ error: 'Not found' }, { status: 404 });
  }
  const root = isGeneratedVideo ? CLASSROOM_VIDEOS_DIR : CLASSROOMS_DIR;
  const filePath = isGeneratedVideo
    ? path.join(root, classroomId, 'clips', pathSegments[1])
    : path.join(root, classroomId, ...pathSegments);
  const resolvedBase = path.resolve(root, classroomId);

  try {
    // Resolve symlinks and verify the real path stays within the classroom dir
    const realPath = await fs.realpath(filePath);
    if (!realPath.startsWith(resolvedBase + path.sep) && realPath !== resolvedBase) {
      return NextResponse.json({ error: 'Not found' }, { status: 404 });
    }

    const stat = await fs.stat(realPath);
    if (!stat.isFile()) {
      return NextResponse.json({ error: 'Not found' }, { status: 404 });
    }

    const ext = path.extname(realPath).toLowerCase();
    const contentType = MIME_TYPES[ext] || 'application/octet-stream';
    const isVideo = ext === '.mp4' || ext === '.webm';
    const etag = `W/"${stat.size}-${stat.mtimeMs}-${stat.ctimeMs}"`;
    const cacheHeaders = { 'Cache-Control': 'private, no-cache', ETag: etag };
    const rangeHeader = isVideo ? req.headers.get('range') : null;
    const requestedRange = rangeHeader &&
      (!req.headers.has('if-range') || req.headers.get('if-range') === etag)
      ? rangeHeader : null;
    if (!requestedRange && req.headers.get('if-none-match') === etag) {
      return new NextResponse(null, { status: 304, headers: cacheHeaders });
    }
    const range = requestedRange ? parseByteRange(requestedRange, stat.size) : null;
    if (requestedRange && !range) {
      return new NextResponse(null, {
        status: 416,
        headers: { ...cacheHeaders, 'Content-Range': `bytes */${stat.size}`, 'Accept-Ranges': 'bytes' },
      });
    }

    // Stream the file to avoid loading large videos into memory
    const stream = createReadStream(realPath, range ? { start: range.start, end: range.end } : undefined);
    const webStream = Readable.toWeb(stream) as ReadableStream<Uint8Array>;

    return new NextResponse(webStream, {
      status: range ? 206 : 200,
      headers: {
        'Content-Type': contentType,
        'Content-Length': String(range ? range.end - range.start + 1 : stat.size),
        ...cacheHeaders,
        ...(isVideo ? { 'Accept-Ranges': 'bytes' } : {}),
        ...(range ? { 'Content-Range': `bytes ${range.start}-${range.end}/${stat.size}` } : {}),
      },
    });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      return NextResponse.json({ error: 'Not found' }, { status: 404 });
    }
    log.error(
      `Classroom media serving failed [classroomId=${classroomId}, path=${joined}]:`,
      error,
    );
    return NextResponse.json({ error: 'Internal error' }, { status: 500 });
  }
}
