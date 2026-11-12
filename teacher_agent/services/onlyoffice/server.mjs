import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { createHash, createHmac, randomBytes, timingSafeEqual } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const configPath = process.env.ONLYOFFICE_PLAYER_CONFIG || '/player-config.json';
const config = JSON.parse(await readFile(configPath, 'utf8'));
const origin = new URL(config.publicOrigin).origin;
const prefix = '/onlyoffice';
const internal = process.env.ONLYOFFICE_PLAYER_INTERNAL || 'http://agentic-onlyoffice-player:3213';
const teacher = process.env.TEACHER_INTERNAL_URL || 'http://agentic-teacher-prod:3200';
const classrooms = process.env.CLASSROOMS_ROOT || '/classrooms';
const sessions = new Map();
const guid = 'asc.{6733E878-467D-46CD-B877-257EB4279BD9}';
const safeId = (v) => typeof v === 'string' && /^[A-Za-z0-9_-]{1,100}$/.test(v);
const digest = (b) => createHash('sha256').update(b).digest('hex');
const sign = (value) => createHmac('sha256', config.jwtSecret).update(value).digest('base64url');
const equal = (a, b) => {
  const x = Buffer.from(a || ''),
    y = Buffer.from(b || '');
  return x.length === y.length && timingSafeEqual(x, y);
};
async function sourceBytes(id, sha) {
  const directory = path.join(classrooms, id, 'native');
  try {
    // Repaired snapshots coexist with the original until old signed URLs expire.
    return await readFile(path.join(directory, `${sha}.pptx`));
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
    return readFile(path.join(directory, 'source.pptx'));
  }
}
const jwt = (payload) => {
  const head = Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' })).toString('base64url');
  const body = Buffer.from(JSON.stringify(payload)).toString('base64url');
  return `${head}.${body}.${sign(`${head}.${body}`)}`;
};
const send = (res, status, body, type = 'application/json; charset=utf-8') => {
  res.writeHead(status, {
    'content-type': type,
    'cache-control': 'no-store',
    'x-content-type-options': 'nosniff',
    'referrer-policy': 'no-referrer',
    'x-frame-options': 'SAMEORIGIN',
  });
  res.end(typeof body === 'object' && !Buffer.isBuffer(body) ? JSON.stringify(body) : body);
};
function pluginConfig(nonce) {
  return {
    name: '原稿放映控制',
    guid,
    version: '1.0.0',
    minVersion: '8.0.0',
    // Docs derives baseUrl from the configuration URL, overriding this value.
    // Keep the variation entry relative to that same session directory.
    baseUrl: `${origin}${prefix}/plugin/session/${nonce}/`,
    variations: [
      {
        description: 'Read-only native presentation playback',
        url: 'index.html',
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
const publicFiles = new Map([
  ['/frame', ['frame.html', 'text/html; charset=utf-8']],
  ['/frame.js', ['frame.js', 'text/javascript; charset=utf-8']],
  ['/plugin/bridge.js', ['bridge.js', 'text/javascript; charset=utf-8']],
]);
const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, origin);
    const route = url.pathname.slice(prefix.length);
    if (!url.pathname.startsWith(prefix + '/') || req.method !== 'GET')
      return send(res, 404, { error: 'Not found' });
    if (route === '/status') {
      const current = JSON.parse(await readFile(configPath, 'utf8'));
      return send(res, 200, {
        enabled: current.nativeEnabled !== false,
        renderer: 'onlyoffice',
        version: 1,
      });
    }
    if (publicFiles.has(route)) {
      const [file, type] = publicFiles.get(route);
      return send(res, 200, await readFile(path.join(root, 'public', file)), type);
    }
    const plugin = /^\/plugin\/session\/([A-Za-z0-9_-]{32})\/(index\.html|config\.json)$/.exec(
      route,
    );
    if (plugin) {
      const s = sessions.get(plugin[1]);
      if (!s || s.expires < Date.now()) return send(res, 403, { error: 'Plugin session expired' });
      return plugin[2] === 'config.json'
        ? send(res, 200, pluginConfig(plugin[1]))
        : send(
            res,
            200,
            await readFile(path.join(root, 'public/plugin.html')),
            'text/html; charset=utf-8',
          );
    }
    const source = /^\/source\/([A-Za-z0-9_-]{1,100})\/([a-f0-9]{64})\.pptx$/.exec(route);
    if (source) {
      const exp = Number(url.searchParams.get('expires'));
      const now = Math.floor(Date.now() / 1000);
      if (
        !Number.isSafeInteger(exp) ||
        exp <= now ||
        exp > now + 3600 ||
        !equal(url.searchParams.get('signature'), sign(`source:${source[1]}:${source[2]}:${exp}`))
      )
        return send(res, 403, { error: 'Source signature invalid or expired' });
      const bytes = await sourceBytes(source[1], source[2]);
      if (digest(bytes) !== source[2]) return send(res, 409, { error: 'Source version changed' });
      return send(
        res,
        200,
        bytes,
        'application/vnd.openxmlformats-officedocument.presentationml.presentation',
      );
    }
    if (route !== '/api/config') return send(res, 404, { error: 'Not found' });
    if (JSON.parse(await readFile(configPath, 'utf8')).nativeEnabled === false)
      return send(res, 503, { error: '原稿播放器已回退' });
    const id = url.searchParams.get('classroom'),
      sceneId = url.searchParams.get('scene');
    if (!safeId(id) || !safeId(sceneId))
      return send(res, 400, { error: 'Invalid classroom or scene' });
    const identityHeaders = {};
    if (/(?:^|;\s*)agentedu_session=/.test(req.headers.cookie || ''))
      identityHeaders.cookie = req.headers.cookie;
    else if (req.headers['x-platform-service-key'] && req.headers['x-platform-subject']) {
      identityHeaders['x-platform-service-key'] = req.headers['x-platform-service-key'];
      identityHeaders['x-platform-subject'] = req.headers['x-platform-subject'];
    }
    if (!Object.keys(identityHeaders).length)
      return send(res, 401, { error: '请先登录课程所属平台' });
    // Delegate every classroom read to the EXISTING ownership check. Caller
    // identity claims are never trusted without that check; upstream is fixed.
    const response = await fetch(`${teacher}/api/classroom?id=${encodeURIComponent(id)}`, {
      headers: identityHeaders,
      redirect: 'manual',
      signal: AbortSignal.timeout(10000),
    });
    if (!response.ok)
      return send(res, response.status === 401 ? 401 : 403, { error: '无权访问此课件' });
    const data = await response.json();
    const classroom = data.classroom;
    const scene = classroom?.scenes?.find((s) => s.id === sceneId);
    const native = classroom?.stage?.nativePptx;
    const page = native?.pages?.[scene?.outlineId];
    if (
      scene?.type !== 'slide' ||
      scene.nativePptxEdited ||
      native?.version !== 1 ||
      !Number.isSafeInteger(page) ||
      page < 1 ||
      page > 2000 ||
      !/^[a-f0-9]{64}$/.test(native.sha256)
    )
      return send(res, 409, { error: '此页的原稿快照不可用，请重新导入原文件' });
    const bytes = await sourceBytes(id, native.sha256);
    if (digest(bytes) !== native.sha256) return send(res, 409, { error: '原稿快照校验失败' });
    const expires = Date.now() + 3600_000,
      exp = Math.floor(expires / 1000),
      nonce = randomBytes(24).toString('base64url');
    for (const [key, value] of sessions) if (value.expires < Date.now()) sessions.delete(key);
    if (sessions.size >= 500) return send(res, 429, { error: 'Too many native playback sessions' });
    sessions.set(nonce, { expires, id });
    const document = {
      fileType: 'pptx',
      key: `native-${native.sha256.slice(0, 48)}`,
      title: classroom.stage.name || '原稿课件',
      url: `${internal}${prefix}/source/${id}/${native.sha256}.pptx?expires=${exp}&signature=${sign(`source:${id}:${native.sha256}:${exp}`)}`,
      permissions: { edit: false, download: false, print: false, comment: false, review: false },
    };
    const editor = {
      documentType: 'slide',
      type: 'desktop',
      width: '100%',
      height: '100%',
      document,
      editorConfig: {
        mode: 'view',
        lang: 'zh-CN',
        customization: { compactHeader: true, compactToolbar: true, hideRightMenu: true },
        plugins: {
          autostart: [guid],
          pluginsData: [`${origin}${prefix}/plugin/session/${nonce}/config.json`],
        },
      },
    };
    const hasNativeClicks = (scene.actions || []).some(
      (a) => a.type === 'reveal' && a.pptxStep?.id?.startsWith('onlyoffice-click-'),
    );
    const steps = (scene.actions || [])
      .filter(
        (a) =>
          a.type === 'reveal' &&
          a.pptxStep &&
          (!hasNativeClicks || a.pptxStep.id.startsWith('onlyoffice-click-')) &&
          !a.pptxStep.effects.every((e) => e.scope === 'slide'),
      )
      .map((a) => Math.max(1, Number(a.duration) || 1));
    const expectedClicks = native.clicks?.[scene.outlineId];
    if (expectedClicks && expectedClicks.length !== steps.length)
      return send(res, 409, { error: '讲解与原稿点击数不一致，请重新生成本页讲解' });
    return send(res, 200, {
      editor: { ...editor, token: jwt({ ...editor, exp }) },
      nonce,
      page,
      steps,
      transitionMs: native.transitions?.[scene.outlineId] || 1400,
      engineUrl: '/onlyoffice-engine/web-apps/apps/api/documents/api.js',
      sceneId,
      compatibility: native.compatibility,
    });
  } catch (e) {
    console.error('NATIVE_PLAYER_ERROR', e.code || e.message);
    send(res, 500, { error: '原稿播放服务暂不可用，请重试' });
  }
});
server.listen(Number(process.env.PORT || 3213), '0.0.0.0', () =>
  console.log('NATIVE_PLAYER_READY ' + server.address().port),
);
