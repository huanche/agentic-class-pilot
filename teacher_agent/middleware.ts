import { NextRequest, NextResponse } from 'next/server';

import { platformMiddleware } from '@/lib/server/platform-auth';
import { renderGrantAllows, verifyRenderGrant } from '@/lib/classroom-video/grant';

/** Convert string to Uint8Array */
function encode(str: string): Uint8Array {
  return new TextEncoder().encode(str);
}

/** Convert ArrayBuffer to hex string */
function bufToHex(buf: ArrayBuffer): string {
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

/** Verify an HMAC-signed token using Web Crypto API (Edge-compatible) */
async function verifyToken(token: string, accessCode: string): Promise<boolean> {
  const dotIndex = token.indexOf('.');
  if (dotIndex === -1) return false;

  const timestamp = token.substring(0, dotIndex);
  const signature = token.substring(dotIndex + 1);

  const keyData = encode(accessCode);
  const key = await crypto.subtle.importKey(
    'raw',
    keyData.buffer as ArrayBuffer,
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );

  const data = encode(timestamp);
  const expected = bufToHex(await crypto.subtle.sign('HMAC', key, data.buffer as ArrayBuffer));

  // Constant-length comparison (not truly constant-time in JS, but sufficient here)
  if (signature.length !== expected.length) return false;
  let mismatch = 0;
  for (let i = 0; i < signature.length; i++) {
    mismatch |= signature.charCodeAt(i) ^ expected.charCodeAt(i);
  }
  return mismatch === 0;
}

export async function middleware(request: NextRequest) {
  const renderSecret = process.env.CLASSROOM_VIDEO_SECRET || process.env.PLATFORM_SERVICE_KEY;
  const renderToken = request.headers.get('x-classroom-render-grant');
  if (renderToken && renderSecret) {
    const grant = await verifyRenderGrant(renderToken, renderSecret);
    if (grant && renderGrantAllows(grant, request.nextUrl, request.method)) {
      const headers = new Headers(request.headers);
      for (const name of ['x-platform-user-id', 'x-platform-admin', 'x-platform-role', 'x-platform-delegated', 'x-platform-service-key', 'x-platform-subject']) headers.delete(name);
      headers.set('x-classroom-render-version', grant.version);
      return NextResponse.next({ request: { headers } });
    }
    return NextResponse.json({ error: 'Invalid render grant' }, { status: 403 });
  }
  request.headers.delete('x-classroom-render-version');
  if (process.env.PLATFORM_AUTH_ENABLED === 'true') {
    // The teacher service owns course creation and teaching-content editing.
    // The platform middleware supplies the authenticated platform identity.
    return platformMiddleware(request);
  }
  const accessCode = process.env.ACCESS_CODE;
  if (!accessCode) {
    return NextResponse.next();
  }

  const { pathname } = request.nextUrl;

  // Whitelist: access-code endpoints, health check
  if (pathname.startsWith('/api/access-code/') || pathname === '/api/health') {
    return NextResponse.next();
  }

  // Check cookie — validate HMAC signature, not just existence
  const cookie = request.cookies.get('openmaic_access');
  if (cookie?.value && (await verifyToken(cookie.value, accessCode))) {
    return NextResponse.next();
  }

  // API requests without valid cookie → 401
  if (pathname.startsWith('/api/')) {
    return NextResponse.json(
      { success: false, errorCode: 'INVALID_REQUEST', error: 'Access code required' },
      { status: 401 },
    );
  }

  // Page requests → let through, frontend shows modal
  return NextResponse.next();
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico|logos/).*)'],
};
