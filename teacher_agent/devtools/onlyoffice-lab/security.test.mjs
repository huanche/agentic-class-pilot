import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import {
  jwt,
  signedDocumentPath,
  verifyDocumentRequest,
  verifyPreviewToken,
  validateBridgeCommand,
} from './security.mjs';
import { CHANNEL, validPeerMessage } from './public/protocol.mjs';

const secret = 'a-unique-lab-secret-with-at-least-32-characters';
const digest = 'abcd'.repeat(16);

test('source capability is tied to the sample digest and expires', () => {
  const url = new URL(signedDocumentPath(secret, digest, 1600), 'https://example.test');
  assert.equal(verifyDocumentRequest(url, secret, digest, 1000), true);
  assert.equal(verifyDocumentRequest(url, secret, 'ef01'.repeat(16), 1000), false);
  assert.equal(verifyDocumentRequest(url, secret, digest, 1600), false);
  url.searchParams.set('expires', '1700');
  assert.equal(verifyDocumentRequest(url, secret, digest, 1000), false);
});

test('source capability cannot authorize other files, long TTLs, or malformed input', () => {
  for (const pathname of [
    '/onlyoffice-test/source.pptx/extra',
    '/onlyoffice-test/config.json',
    '/etc/passwd',
  ]) {
    const url = new URL(signedDocumentPath(secret, digest, 1600), 'https://example.test');
    url.pathname = pathname;
    assert.equal(verifyDocumentRequest(url, secret, digest, 1000), false);
  }
  const long = new URL(signedDocumentPath(secret, digest, 5000), 'https://example.test');
  assert.equal(verifyDocumentRequest(long, secret, digest, 1000), false);
  assert.equal(
    verifyDocumentRequest(
      new URL('https://example.test/onlyoffice-test/source.pptx?expires=NaN'),
      secret,
      digest,
      1000,
    ),
    false,
  );
});

test('preview access is a fixed, expiring lab capability', () => {
  const config = { previewToken: 'x'.repeat(43), previewExpiresAt: 2000 };
  assert.equal(verifyPreviewToken('x'.repeat(43), config, 1000), true);
  for (const token of [undefined, 'x', 'y'.repeat(43)])
    assert.equal(verifyPreviewToken(token, config, 1000), false);
  assert.equal(verifyPreviewToken(config.previewToken, config, 2000), false);
});

test('ONLYOFFICE config JWT is HS256 and covers the full document config', () => {
  const token = jwt(
    { document: { key: 'sample', permissions: { edit: false } }, exp: 2000 },
    secret,
  );
  const [header, body, signature] = token.split('.');
  assert.equal(JSON.parse(Buffer.from(header, 'base64url')).alg, 'HS256');
  assert.equal(JSON.parse(Buffer.from(body, 'base64url')).document.permissions.edit, false);
  assert.equal(
    signature,
    createHmac('sha256', secret).update(`${header}.${body}`).digest('base64url'),
  );
  assert.throws(() => jwt({}, 'weak'));
});

test('bridge ignores messages from another origin, session, or window', () => {
  const peer = {};
  const good = {
    origin: 'https://example.test',
    source: peer,
    data: { channel: CHANNEL, nonce: 'abc' },
  };
  assert.equal(validPeerMessage(good, good.origin, 'abc', peer), true);
  assert.equal(
    validPeerMessage({ ...good, origin: 'https://attacker.test' }, good.origin, 'abc', peer),
    false,
  );
  assert.equal(validPeerMessage(good, good.origin, 'other', peer), false);
  assert.equal(validPeerMessage({ ...good, source: {} }, good.origin, 'abc', peer), false);
  assert.equal(validPeerMessage({ ...good, source: null }, good.origin, 'abc', null), false);
});

test('bridge allows navigation in the five-page sample, never arbitrary editor methods', () => {
  for (const command of ['start', 'end', 'advance', 'pause', 'resume'])
    assert.equal(validateBridgeCommand({ id: 1, command }), true);
  for (const page of [1, 5])
    assert.equal(validateBridgeCommand({ id: 1, command: 'goto', page }), true);
  for (const page of [0, 6, 1.5, '2'])
    assert.equal(validateBridgeCommand({ id: 1, command: 'goto', page }), false);
  for (const command of ['callCommand', 'InstallPlugin', 'SetMacros'])
    assert.equal(validateBridgeCommand({ id: 1, command }), false);
  assert.equal(validateBridgeCommand({ id: -1, command: 'start' }), false);
});
