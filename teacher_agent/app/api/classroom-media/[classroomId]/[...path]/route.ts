import { promises as fs, createReadStream } from 'fs';
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
  _req: NextRequest,
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

  // Only allow media/ and audio/ subdirectories
  const subDir = pathSegments[0];
  if (subDir !== 'media' && subDir !== 'audio' && subDir !== 'video') {
    return NextResponse.json({ error: 'Invalid path' }, { status: 404 });
  }

  const isVideo = subDir === 'video';
  if (isVideo && (pathSegments.length !== 2 || !/^[a-f0-9]{64}\.mp4$/.test(pathSegments[1])))
    return NextResponse.json({ error: 'Not found' }, { status: 404 });
  if (isVideo && _req.headers.get('x-platform-role') === 'student') {
    const pointer = await videoPointer(classroomId, 'published');
    const plan = pointer && await readVideoPlan(classroomId, pointer.version);
    if (!plan || !plan.clips.some((c) => `${c.key}.mp4` === pathSegments[1]))
      return NextResponse.json({ error: 'Not found' }, { status: 404 });
  }
  const root = isVideo ? CLASSROOM_VIDEOS_DIR : CLASSROOMS_DIR;
  const filePath = isVideo ? path.join(root, classroomId, 'clips', pathSegments[1]) : path.join(root, classroomId, ...pathSegments);
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

    // Stream the file to avoid loading large videos into memory
    const rangeHeader = _req.headers.get('range');
    const range = rangeHeader ? parseByteRange(rangeHeader, stat.size) : undefined;
    if (range === null) return new NextResponse(null, { status: 416,
      headers: { 'Content-Range': `bytes */${stat.size}`, 'Accept-Ranges': 'bytes' } });
    const stream = createReadStream(realPath, range || undefined);
    const webStream = new ReadableStream({
      start(controller) {
        stream.on('data', (chunk: Buffer | string) => controller.enqueue(chunk));
        stream.on('end', () => controller.close());
        stream.on('error', (err) => controller.error(err));
      },
      cancel() {
        stream.destroy();
      },
    });

    return new NextResponse(webStream, {
      status: range ? 206 : 200,
      headers: {
        'Content-Type': contentType,
        'Content-Length': String(range ? range.end - range.start + 1 : stat.size),
        'Accept-Ranges': 'bytes',
        ...(range ? { 'Content-Range': `bytes ${range.start}-${range.end}/${stat.size}` } : {}),
        // Narration files are regenerated in place under stable names (server
        // narration re-runs and browser TTS re-uploads both overwrite
        // `tts_s<order>_<actionId>.<ext>`), so audio must always revalidate —
        // an immutable entry would pin superseded bytes for a day. Slide media
        // is content-final and stays immutable-cacheable.
        'Cache-Control':
          isVideo ? 'private, max-age=86400, immutable' : subDir === 'audio' ? 'private, no-cache' : 'public, max-age=86400, immutable',
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
