import { createHmac, timingSafeEqual } from 'node:crypto';

export const LAB_PREFIX = '/onlyoffice-test';
export const ENGINE_PREFIX = '/onlyoffice-engine';
export const BRIDGE_GUID = 'asc.{6733E878-467D-46CD-B877-257EB4279BD8}';
export const BRIDGE_CHANNEL = 'agentic-onlyoffice-v1';
export { validCommand as validateBridgeCommand } from './public/protocol.mjs';

function equal(a, b) {
  const left = Buffer.from(a || '');
  const right = Buffer.from(b || '');
  return left.length === right.length && timingSafeEqual(left, right);
}

export function jwt(payload, secret) {
  if (!secret || secret.length < 32) throw new Error('A dedicated JWT secret is required');
  const header = Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' })).toString('base64url');
  const body = Buffer.from(JSON.stringify(payload)).toString('base64url');
  const signature = createHmac('sha256', secret).update(`${header}.${body}`).digest('base64url');
  return `${header}.${body}.${signature}`;
}

export function verifyPreviewToken(token, config, now = Date.now()) {
  return (
    Number.isSafeInteger(config.previewExpiresAt) &&
    config.previewExpiresAt > now &&
    typeof config.previewToken === 'string' &&
    config.previewToken.length >= 43 &&
    equal(token, config.previewToken)
  );
}

export function signedDocumentPath(secret, digest, expires) {
  const signature = createHmac('sha256', secret)
    .update(`source:${digest}:${expires}`)
    .digest('base64url');
  return `${LAB_PREFIX}/source.pptx?expires=${expires}&signature=${signature}`;
}

export function verifyDocumentRequest(
  url,
  secret,
  digest,
  nowSeconds = Math.floor(Date.now() / 1000),
) {
  const expires = Number(url.searchParams.get('expires'));
  if (
    url.pathname !== `${LAB_PREFIX}/source.pptx` ||
    !Number.isSafeInteger(expires) ||
    expires <= nowSeconds ||
    expires > nowSeconds + 3600
  )
    return false;
  const expected = new URL(signedDocumentPath(secret, digest, expires), 'http://local');
  return equal(url.searchParams.get('signature'), expected.searchParams.get('signature'));
}
