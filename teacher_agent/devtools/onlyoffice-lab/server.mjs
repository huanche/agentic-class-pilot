import http from 'node:http';
import { readFile, appendFile } from 'node:fs/promises';
import { createHash, randomBytes } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  LAB_PREFIX,
  ENGINE_PREFIX,
  BRIDGE_GUID,
  jwt,
  verifyPreviewToken,
  signedDocumentPath,
  verifyDocumentRequest,
} from './security.mjs';

const root = path.dirname(fileURLToPath(import.meta.url));
const configPath = process.env.ONLYOFFICE_LAB_CONFIG || '/lab-state/config.json';
const dataRoot = process.env.ONLYOFFICE_LAB_DATA || '/lab-data';
const config = JSON.parse(await readFile(configPath, 'utf8'));
const source = await readFile(path.join(dataRoot, 'five-pages.pptx'));
const sourceDigest = createHash('sha256').update(source).digest('hex');
const sample = JSON.parse(await readFile(path.join(dataRoot, 'sample.json'), 'utf8'));
if (sample.pages.length !== 5 || sample.sampleSha256 !== sourceDigest) {
  throw new Error('The lab must use the verified five-page sample');
}
const origin = new URL(config.publicOrigin).origin;
const sessions = new Map();
const publicFiles = new Map([
  [`${LAB_PREFIX}/`, ['index.html', 'text/html; charset=utf-8']],
  [`${LAB_PREFIX}/app.js`, ['app.js', 'text/javascript; charset=utf-8']],
  [`${LAB_PREFIX}/style.css`, ['style.css', 'text/css; charset=utf-8']],
  [`${LAB_PREFIX}/protocol.mjs`, ['protocol.mjs', 'text/javascript; charset=utf-8']],
  [`${LAB_PREFIX}/plugin/index.html`, ['plugin/index.html', 'text/html; charset=utf-8']],
  [`${LAB_PREFIX}/plugin/bridge.js`, ['plugin/bridge.js', 'text/javascript; charset=utf-8']],
]);

function send(res, status, body, type = 'application/json; charset=utf-8') {
  res.writeHead(status, {
    'content-type': type,
    'cache-control': 'no-store',
    'x-content-type-options': 'nosniff',
    'referrer-policy': 'no-referrer',
    'x-frame-options': 'SAMEORIGIN',
  });
  res.end(typeof body === 'object' && !Buffer.isBuffer(body) ? JSON.stringify(body) : body);
}

async function principal(req) {
  const bearer = /^Bearer (\S+)$/.exec(req.headers.authorization || '')?.[1];
  if (verifyPreviewToken(bearer, config)) return { userId: config.ownerId, preview: true };
  const cookie = /(?:^|;\s*)agentedu_session=([^;]+)/.exec(req.headers.cookie || '')?.[1];
  if (!cookie) return null;
  try {
    const response = await fetch(
      `${process.env.PLATFORM_AUTH_URL}/api/v1/internal/teacher/authorize`,
      {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          'x-teacher-service-key': process.env.PLATFORM_SERVICE_KEY || '',
        },
        body: JSON.stringify({
          cookie,
          method: 'GET',
          origin,
          path: `/course-space/${config.courseId}`,
        }),
        signal: AbortSignal.timeout(5000),
      },
    );
    if (!response.ok) return null;
    const identity = await response.json();
    return identity.userId === config.ownerId ? identity : null;
  } catch {
    return null;
  }
}

function pluginConfig(nonce) {
  return {
    name: '课件配音同步试验',
    guid: BRIDGE_GUID,
    version: '0.1.0',
    minVersion: '8.0.0',
    baseUrl: `${origin}${LAB_PREFIX}/plugin/`,
    variations: [
      {
        description: 'Synchronize the five-page read-only PPTX test with narration.',
        url: `session/${nonce}/index.html`,
        EditorsSupport: ['slide'],
        type: 'background',
        isSystem: true,
        isVisual: false,
        isViewer: true,
        isDisplayedInViewer: true,
        initDataType: 'none',
        initData: '',
        buttons: [],
      },
    ],
  };
}

async function receiveJson(req) {
  const parts = [];
  let size = 0;
  for await (const part of req) {
    size += part.length;
    if (size > 65536) throw new Error('Request too large');
    parts.push(part);
  }
  return JSON.parse(Buffer.concat(parts).toString('utf8'));
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, origin);
    const pathname = url.pathname;
    if (pathname === `${LAB_PREFIX}/health` && req.method === 'GET') {
      send(res, 200, { ok: true, pages: 5, sourceDigest, mode: 'read-only-lab' });
      return;
    }
    if (pathname === `${LAB_PREFIX}/source.pptx` && ['GET', 'HEAD'].includes(req.method)) {
      if (!verifyDocumentRequest(url, config.jwtSecret, sourceDigest)) {
        send(res, 403, { error: 'Source capability expired or invalid' });
        return;
      }
      res.writeHead(200, {
        'content-type': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'content-length': source.length,
        'cache-control': 'no-store',
      });
      res.end(req.method === 'HEAD' ? undefined : source);
      return;
    }
    if (pathname === `${LAB_PREFIX}/plugin/config.json` && req.method === 'GET') {
      const nonce = url.searchParams.get('nonce');
      const session = sessions.get(nonce);
      if (!session || session.expires <= Date.now()) {
        send(res, 403, { error: 'Plugin session expired' });
        return;
      }
      send(res, 200, pluginConfig(nonce));
      return;
    }
    const pluginPage = new RegExp(
      `^${LAB_PREFIX}/plugin/session/([A-Za-z0-9_-]{32})/(index\\.html|config\\.json)$`,
    ).exec(pathname);
    if (pluginPage && req.method === 'GET') {
      const session = sessions.get(pluginPage[1]);
      if (!session || session.expires <= Date.now()) {
        send(res, 403, { error: 'Plugin session expired' });
        return;
      }
      if (pluginPage[2] === 'config.json') send(res, 200, pluginConfig(pluginPage[1]));
      else
        send(
          res,
          200,
          await readFile(path.join(root, 'public/plugin/index.html')),
          'text/html; charset=utf-8',
        );
      return;
    }
    if (publicFiles.has(pathname) && req.method === 'GET') {
      const [name, type] = publicFiles.get(pathname);
      send(res, 200, await readFile(path.join(root, 'public', name)), type);
      return;
    }
    if (!pathname.startsWith(`${LAB_PREFIX}/api/`)) {
      send(res, 404, { error: 'Not found' });
      return;
    }
    const identity = await principal(req);
    if (!identity) {
      send(res, 401, { error: '请使用此课程所属教师账号登录后重试。' });
      return;
    }
    if (pathname === `${LAB_PREFIX}/api/config` && req.method === 'GET') {
      const nonce = randomBytes(24).toString('base64url');
      const expires = Date.now() + 3600_000;
      for (const [id, session] of sessions) if (session.expires < Date.now()) sessions.delete(id);
      if (sessions.size > 100) {
        send(res, 429, { error: 'Too many preview sessions' });
        return;
      }
      sessions.set(nonce, { expires, userId: identity.userId });
      const editor = {
        documentType: 'slide',
        type: 'desktop',
        width: '100%',
        height: '100%',
        document: {
          fileType: 'pptx',
          key: `agentic-lab-${sourceDigest.slice(0, 40)}`,
          title: '第九章 指针 · 原稿第 5—9 页',
          url:
            config.internalOrigin +
            signedDocumentPath(config.jwtSecret, sourceDigest, Math.floor(expires / 1000)),
          permissions: {
            edit: false,
            download: false,
            print: false,
            comment: false,
            review: false,
          },
        },
        editorConfig: {
          mode: 'view',
          lang: 'zh-CN',
          user: { id: identity.userId, name: '教师' },
          customization: { compactHeader: true, compactToolbar: true, hideRightMenu: true },
          plugins: {
            autostart: [BRIDGE_GUID],
            pluginsData: [`${origin}${LAB_PREFIX}/plugin/config.json?nonce=${nonce}`],
          },
        },
      };
      send(res, 200, {
        editor: {
          ...editor,
          token: jwt({ ...editor, exp: Math.floor(expires / 1000) }, config.jwtSecret),
        },
        nonce,
        sample,
        engineUrl: `${ENGINE_PREFIX}/web-apps/apps/api/documents/api.js`,
      });
      return;
    }
    const audio = new RegExp(`^${LAB_PREFIX}/api/audio/(p[1-5]_c[0-9]{1,2}\\.wav)$`).exec(pathname);
    if (audio && ['GET', 'HEAD'].includes(req.method)) {
      if (!sample.pages.some((page) => page.cues.some((cue) => cue.audio === audio[1]))) {
        send(res, 404, { error: 'Unknown cue' });
        return;
      }
      const bytes = await readFile(path.join(dataRoot, 'audio', audio[1]));
      res.writeHead(200, {
        'content-type': 'audio/wav',
        'content-length': bytes.length,
        'cache-control': 'private, max-age=3600',
      });
      res.end(req.method === 'HEAD' ? undefined : bytes);
      return;
    }
    if (pathname === `${LAB_PREFIX}/api/telemetry` && req.method === 'POST') {
      if (req.headers.origin !== origin) {
        send(res, 403, { error: 'Invalid origin' });
        return;
      }
      const body = await receiveJson(req);
      if (!Array.isArray(body.events) || body.events.length > 100) {
        send(res, 400, { error: 'Invalid events' });
        return;
      }
      const safe = body.events.map((event) => ({
        event: typeof event.event === 'string' ? event.event.slice(0, 80) : 'unknown',
        page: Number.isInteger(event.page) ? event.page : null,
        cue: Number.isInteger(event.cue) ? event.cue : null,
        at: Number.isFinite(event.at) ? event.at : null,
        detail: typeof event.detail === 'string' ? event.detail.slice(0, 200) : '',
      }));
      await appendFile(
        path.join(config.stateDir, 'playback.jsonl'),
        JSON.stringify({ at: Date.now(), events: safe }) + '\n',
      );
      send(res, 200, { ok: true });
      return;
    }
    send(res, 404, { error: 'Not found' });
  } catch (error) {
    console.error('OnlyOffice lab request failed:', error?.code || error?.message);
    if (!res.headersSent) send(res, 500, { error: '测试服务暂不可用，请重试。' });
    else res.destroy();
  }
});

server.listen(Number(process.env.PORT || 3212), '0.0.0.0', () => {
  console.log(`ONLYOFFICE_LAB_READY pages=5 digest=${sourceDigest} PORT=${server.address().port}`);
});
