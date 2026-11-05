// Read-only, expiring capability for the isolated video renderer. Never a
// platform login/session: it cannot edit content or read another classroom.
export interface RenderGrant {
  id: string;
  version: string;
  exp: number;
}
const safe = /^[A-Za-z0-9_-]{1,100}$/;
export function renderGrantAllows(claims: RenderGrant, url: URL, method: string) {
  if (!['GET', 'HEAD'].includes(method)) return false;
  if (url.pathname === `/classroom-player/${claims.id}`)
    return url.searchParams.get('capture') === claims.version;
  if (url.pathname === '/api/classroom')
    return (
      url.searchParams.get('id') === claims.id &&
      url.searchParams.get('videoCapture') === claims.version
    );
  return url.pathname.startsWith(`/api/classroom-media/${claims.id}/media/`);
}
async function signature(value: string, secret: string) {
  const key = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  return Array.from(
    new Uint8Array(await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(value))),
  )
    .map((n) => n.toString(16).padStart(2, '0'))
    .join('');
}
export async function signRenderGrant(claims: RenderGrant, secret: string) {
  const value = `${claims.id}.${claims.version}.${claims.exp}`;
  return `${value}.${await signature(value, secret)}`;
}
export async function verifyRenderGrant(
  token: string,
  secret: string,
  now = Date.now(),
): Promise<RenderGrant | null> {
  const [id, version, expires, sig, extra] = token.split('.');
  const exp = Number(expires);
  if (
    extra ||
    !safe.test(id || '') ||
    !/^[a-f0-9]{64}$/.test(version || '') ||
    !Number.isSafeInteger(exp) ||
    exp <= now ||
    exp > now + 7 * 3600_000 ||
    !sig
  )
    return null;
  const expected = await signature(`${id}.${version}.${expires}`, secret);
  if (sig.length !== expected.length) return null;
  let mismatch = 0;
  for (let i = 0; i < sig.length; i++) mismatch |= sig.charCodeAt(i) ^ expected.charCodeAt(i);
  return mismatch ? null : { id, version, exp };
}
