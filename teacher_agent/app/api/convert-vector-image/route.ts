import { execFile } from 'node:child_process';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { promisify } from 'node:util';
import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';

const execFileAsync = promisify(execFile);
const MAX_VECTOR_IMAGE_BYTES = 10 * 1024 * 1024;

// GDI+ is available on the Windows host that runs the local education
// platform and reliably renders the WMF previews embedded by MathType.
const POWERSHELL_WMF_TO_PNG = `
Add-Type -AssemblyName System.Drawing
$source = $env:OPENMAIC_WMF_SOURCE
$target = $env:OPENMAIC_WMF_TARGET
$image = [System.Drawing.Image]::FromFile($source)
try {
  $bitmap = New-Object System.Drawing.Bitmap($image.Width, $image.Height, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
  try {
    $bitmap.SetResolution($image.HorizontalResolution, $image.VerticalResolution)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
      $graphics.Clear([System.Drawing.Color]::Transparent)
      $graphics.DrawImage($image, 0, 0, $image.Width, $image.Height)
    } finally { $graphics.Dispose() }
    $bitmap.Save($target, [System.Drawing.Imaging.ImageFormat]::Png)
  } finally { $bitmap.Dispose() }
} finally { $image.Dispose() }
`;

export async function POST(request: NextRequest) {
  if (request.nextUrl.searchParams.get('format')?.toLowerCase() !== 'wmf') {
    return NextResponse.json({ error: 'Only WMF conversion is supported' }, { status: 400 });
  }

  const declaredLength = Number(request.headers.get('content-length') || 0);
  if (declaredLength > MAX_VECTOR_IMAGE_BYTES) {
    return NextResponse.json({ error: 'Vector image is too large' }, { status: 413 });
  }

  const bytes = Buffer.from(await request.arrayBuffer());
  if (!bytes.length || bytes.length > MAX_VECTOR_IMAGE_BYTES) {
    return NextResponse.json(
      { error: bytes.length ? 'Vector image is too large' : 'Empty vector image' },
      { status: bytes.length ? 413 : 400 },
    );
  }
  if (process.platform !== 'win32') {
    return NextResponse.json(
      { error: 'WMF conversion requires the Windows rendering service' },
      { status: 501 },
    );
  }

  const workDir = await mkdtemp(join(tmpdir(), 'openmaic-wmf-'));
  const sourcePath = join(workDir, 'source.wmf');
  const targetPath = join(workDir, 'rendered.png');
  try {
    await writeFile(sourcePath, bytes);
    const encodedCommand = Buffer.from(POWERSHELL_WMF_TO_PNG, 'utf16le').toString('base64');
    await execFileAsync(
      'powershell.exe',
      ['-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encodedCommand],
      {
        timeout: 15_000,
        windowsHide: true,
        env: {
          ...process.env,
          OPENMAIC_WMF_SOURCE: sourcePath,
          OPENMAIC_WMF_TARGET: targetPath,
        },
      },
    );
    const png = await readFile(targetPath);
    return new NextResponse(png, {
      headers: {
        'content-type': 'image/png',
        'cache-control': 'private, max-age=31536000, immutable',
      },
    });
  } catch (error) {
    console.error('[convert-vector-image] WMF conversion failed:', error);
    return NextResponse.json({ error: 'WMF conversion failed' }, { status: 422 });
  } finally {
    await rm(workDir, { recursive: true, force: true });
  }
}
