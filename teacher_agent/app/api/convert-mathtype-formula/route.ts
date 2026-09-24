import { spawn } from 'node:child_process';
import { join } from 'node:path';
import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';

const MAX_OLE_BYTES = 10 * 1024 * 1024;
const MAX_OUTPUT_BYTES = 2 * 1024 * 1024;

function convertOleToMathMl(payload: Buffer): Promise<string> {
  return new Promise((resolve, reject) => {
    const python = process.env.OPENMAIC_PYTHON_BIN || 'python';
    const script = join(process.cwd(), 'scripts', 'convert-mathtype-ole.py');
    const child = spawn(python, [script], {
      cwd: process.cwd(),
      windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    const stdout: Buffer[] = [];
    const stderr: Buffer[] = [];
    let outputSize = 0;
    const timer = setTimeout(() => child.kill(), 15_000);

    child.stdout.on('data', (chunk: Buffer) => {
      outputSize += chunk.length;
      if (outputSize > MAX_OUTPUT_BYTES) child.kill();
      else stdout.push(chunk);
    });
    child.stderr.on('data', (chunk: Buffer) => stderr.push(chunk));
    child.on('error', reject);
    child.on('close', (code) => {
      clearTimeout(timer);
      if (code !== 0 || outputSize > MAX_OUTPUT_BYTES) {
        reject(new Error(Buffer.concat(stderr).toString('utf8') || `converter exited ${code}`));
        return;
      }
      try {
        const result = JSON.parse(Buffer.concat(stdout).toString('utf8')) as { mathml?: unknown };
        if (typeof result.mathml !== 'string' || !result.mathml.includes('<math')) {
          throw new Error('converter returned no MathML');
        }
        resolve(result.mathml);
      } catch (error) {
        reject(error);
      }
    });
    child.stdin.end(payload);
  });
}

export async function POST(request: NextRequest) {
  const declaredLength = Number(request.headers.get('content-length') || 0);
  if (declaredLength > MAX_OLE_BYTES) {
    return NextResponse.json({ error: 'Formula object is too large' }, { status: 413 });
  }
  const payload = Buffer.from(await request.arrayBuffer());
  if (!payload.length || payload.length > MAX_OLE_BYTES) {
    return NextResponse.json(
      { error: payload.length ? 'Formula object is too large' : 'Empty formula object' },
      { status: payload.length ? 413 : 400 },
    );
  }

  try {
    const mathml = await convertOleToMathMl(payload);
    return NextResponse.json({ mathml });
  } catch (error) {
    console.error('[convert-mathtype-formula] conversion failed:', error);
    return NextResponse.json({ error: 'MathType formula conversion failed' }, { status: 422 });
  }
}
