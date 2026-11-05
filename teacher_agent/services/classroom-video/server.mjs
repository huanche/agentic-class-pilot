import http from 'node:http';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { spawn } from 'node:child_process';
import { timingSafeEqual, randomUUID } from 'node:crypto';
import { chromium } from 'playwright-core';
import { prepareRecordingWithRetry } from './readiness.mjs';

const root = process.env.CLASSROOM_VIDEOS_DIR || '/videos';
const origin = new URL(process.env.VIDEO_PUBLIC_ORIGIN || 'https://agenticclasspilot.com').origin;
const teacher = process.env.VIDEO_TEACHER_URL || 'http://agentic-teacher-prod:3200';
const secret = process.env.CLASSROOM_VIDEO_WORKER_KEY;
if (!secret || secret.length < 32) throw new Error('A private worker key is required');
const jobs = new Map(),
  queue = [];
let active = false;
const safeId = (v) => typeof v === 'string' && /^[A-Za-z0-9_-]{1,100}$/.test(v);
const safeHash = (v) => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
function equal(value) {
  const a = Buffer.from(value || ''),
    b = Buffer.from(secret);
  return a.length === b.length && timingSafeEqual(a, b);
}
async function atomic(file, data) {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const tmp = `${file}.${randomUUID()}.tmp`;
  await fs.writeFile(tmp, JSON.stringify(data));
  await fs.rename(tmp, file);
}
const reply = (r, status, body) => {
  r.writeHead(status, { 'content-type': 'application/json', 'cache-control': 'no-store' });
  r.end(JSON.stringify(body));
};
async function command(bin, args, timeout = 120_000) {
  return new Promise((resolve, reject) => {
    const child = spawn(bin, args, { stdio: ['ignore', 'pipe', 'pipe'] });
    let out = '',
      err = '';
    child.stdout.on('data', (b) => {
      if (out.length < 1_000_000) out += b;
    });
    child.stderr.on('data', (b) => {
      err = (err + b).slice(-8000);
    });
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
    }, timeout);
    child.on('error', (e) => {
      clearTimeout(timer);
      reject(e);
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      code === 0 ? resolve(out) : reject(new Error(`${bin} failed (${code}): ${err.slice(-1000)}`));
    });
  });
}
async function probe(file) {
  return JSON.parse(
    await command('ffprobe', ['-v', 'error', '-show_format', '-show_streams', '-of', 'json', file]),
  );
}
async function bounded(promise, ms, message) {
  let timer;
  try {
    return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(message)), ms); })]);
  } finally { clearTimeout(timer); }
}
async function capture(job, plan, clip, onPhase) {
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'classroom-video-'));
  let browser, page;
  const writes = [];
  try {
    const durations = {};
    for (const [actionId, audio] of Object.entries(clip.audio)) {
      if (!/^[a-f0-9]{64}\.(wav|mp3|ogg|aac)$/.test(audio.file))
        throw new Error('Invalid audio snapshot');
      const info = await probe(path.join(root, plan.id, 'assets', audio.file));
      const duration = Number(info.format?.duration);
      if (!info.streams.some((s) => s.codec_type === 'audio') || !(duration > 0 && duration < 600))
        throw new Error('配音文件无效');
      durations[actionId] = duration;
    }
    const narrationSeconds = Object.values(durations).reduce((a, b) => a + b, 0);
    if (narrationSeconds > 900) throw new Error('单页讲解超过十五分钟，请拆分页面');
    const args = [
      '--disable-dev-shm-usage',
      '--no-sandbox',
      '--autoplay-policy=no-user-gesture-required',
    ];
    if (process.env.VIDEO_ORIGIN_IP)
      args.push(
        `--host-resolver-rules=MAP ${new URL(origin).hostname} ${process.env.VIDEO_ORIGIN_IP}`,
      );
    browser = await chromium.launch({
      executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium',
      headless: true,
      args,
    });
    const context = await browser.newContext({
      viewport: { width: 1280, height: 720 },
      deviceScaleFactor: 1,
      serviceWorkers: 'block',
    });
    page = await context.newPage();
    page.setDefaultTimeout(90_000);
    const json = async (suffix) => {
      const response = await fetch(
        `${teacher}/api/classroom?id=${plan.id}&videoCapture=${plan.version}${suffix}`,
        { headers: { 'x-classroom-render-grant': job.grant }, signal: AbortSignal.timeout(30_000) },
      );
      if (!response.ok) throw new Error(`渲染快照读取失败 (${response.status})`);
      return response.json();
    };
    // The browser receives only a short-lived classroom-scoped read capability.
    // No platform session, service key or arbitrary outbound network is exposed.
    await context.route('**/*', async (route) => {
      const request = route.request(),
        url = new URL(request.url());
      if (['data:', 'blob:'].includes(url.protocol)) return route.continue();
      if (url.origin !== origin || !['GET', 'HEAD'].includes(request.method()))
        return route.abort();
      if (url.pathname === '/onlyoffice/api/config') {
        if (
          url.searchParams.get('classroom') !== plan.id ||
          url.searchParams.get('scene') !== clip.sceneId
        )
          return route.abort();
        try {
          const body = await json(`&nativeScene=${clip.sceneId}`);
          return route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(body.nativeConfig),
          });
        } catch {
          return route.fulfill({
            status: 503,
            contentType: 'application/json',
            body: JSON.stringify({ error: '原稿引擎配置失败' }),
          });
        }
      }
      const headers = { ...request.headers() };
      if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/classroom-player/'))
        headers['x-classroom-render-grant'] = job.grant;
      // Private canary: exercise a candidate app without changing the gateway
      // used by active classes. The destination is operator-configured only.
      if (
        process.env.VIDEO_CAPTURE_PROXY_TEACHER === 'true' &&
        !url.pathname.startsWith('/onlyoffice')
      ) {
        const response = await route.fetch({
          url: `${teacher}${url.pathname}${url.search}`,
          headers,
        });
        return route.fulfill({ response });
      }
      return route.continue({ headers });
    });
    await page.goto(`${origin}/classroom-player/${plan.id}?capture=${plan.version}`, {
      waitUntil: 'domcontentloaded',
    });
    await page.waitForFunction(() => window.classroomCapture || window.classroomCaptureError);
    await prepareRecordingWithRetry(page, clip.sceneId, onPhase);
    const cdp = await context.newCDPSession(page);
    const frames = [];
    let byteCount = 0, rejectCapture;
    const captureFailure = new Promise((_, reject) => { rejectCapture = reject; });
    void captureFailure.catch(() => {});
    let firstResolve;
    const first = new Promise((resolve) => {
      firstResolve = resolve;
    });
    cdp.on('Page.screencastFrame', (event) => {
      const n = frames.length;
      void cdp.send('Page.screencastFrameAck', { sessionId: event.sessionId }).catch(() => {});
      const bytes = Buffer.from(event.data, 'base64');
      byteCount += bytes.length;
      if (n > 30_000 || byteCount > 800 * 1024 * 1024) { rejectCapture(new Error('单页动画过大，请拆分页面后重试')); return; }
      const file = `frame-${String(n).padStart(6, '0')}.jpg`;
      frames.push({ file, epoch: event.metadata.timestamp * 1000 });
      writes.push(fs.writeFile(path.join(temp, file), bytes).catch(rejectCapture));
      firstResolve();
    });
    await cdp.send('Page.startScreencast', {
      format: 'jpeg',
      quality: 92,
      maxWidth: 1280,
      maxHeight: 720,
      everyNthFrame: 1,
    });
    await Promise.race([
      first,
      new Promise((_, reject) => setTimeout(() => reject(new Error('视频采集未返回画面')), 15_000)),
    ]);
    const result = await bounded(Promise.race([page.evaluate((d) => window.classroomCapture.run(d), durations), captureFailure]),
      (narrationSeconds + 300) * 1000, '此页录制超时，请重试未完成视频');
    await cdp.send('Page.stopScreencast');
    await Promise.all(writes);
    const start = frames[0].epoch;
    const duration = (result.endEpoch - start) / 1000;
    if (!(duration > 0 && duration < 7200) || frames.some((f) => !Number.isFinite(f.epoch)))
      throw new Error('无效的视频时间轴');
    let concat = '';
    for (let i = 0; i < frames.length; i++) {
      const until = frames[i + 1]?.epoch ?? result.endEpoch;
      concat += `file '${frames[i].file}'\nduration ${Math.max(0.001, (until - frames[i].epoch) / 1000)}\n`;
    }
    concat += `file '${frames.at(-1).file}'\n`;
    await fs.writeFile(path.join(temp, 'frames.txt'), concat);
    const argsFF = [
      '-hide_banner',
      '-loglevel',
      'error',
      '-y',
      '-f',
      'concat',
      '-safe',
      '1',
      '-i',
      path.join(temp, 'frames.txt'),
    ];
    const filters = [],
      labels = [];
    for (let i = 0; i < result.speech.length; i++) {
      const cue = result.speech[i],
        asset = clip.audio[cue.actionId];
      if (!asset) throw new Error('讲稿配音未匹配');
      argsFF.push('-i', path.join(root, plan.id, 'assets', asset.file));
      const offset = Math.max(0, Math.round(cue.epoch - start));
      filters.push(`[${i + 1}:a]aresample=48000,adelay=${offset}:all=1[a${i}]`);
      labels.push(`[a${i}]`);
    }
    if (!labels.length) throw new Error('录制没有配音事件');
    filters.push(`${labels.join('')}amix=inputs=${labels.length}:normalize=0[mix]`);
    const output = path.join(temp, 'output.mp4');
    argsFF.push(
      '-filter_complex_threads',
      '2',
      '-filter_complex',
      filters.join(';'),
      '-map',
      '0:v',
      '-map',
      '[mix]',
      '-vf',
      'fps=30,scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2',
      '-c:v',
      'libx264',
      '-threads',
      '2',
      '-preset',
      'veryfast',
      '-crf',
      '20',
      '-pix_fmt',
      'yuv420p',
      '-c:a',
      'aac',
      '-b:a',
      '128k',
      '-movflags',
      '+faststart',
      '-t',
      String(duration),
      output,
    );
    await onPhase('encoding');
    await command('ffmpeg', argsFF, 900_000);
    const info = await probe(output);
    if (
      !info.streams.some((s) => s.codec_type === 'video' && s.codec_name === 'h264') ||
      !info.streams.some((s) => s.codec_type === 'audio' && s.codec_name === 'aac') ||
      Math.abs(Number(info.format.duration) - duration) > 0.5
    )
      throw new Error('生成的视频音画校验未通过');
    const dest = path.join(root, plan.id, 'clips', `${clip.key}.mp4`);
    await fs.mkdir(path.dirname(dest), { recursive: true });
    // Same filesystem publication: readers never see a partial MP4.
    const staging = `${dest}.${randomUUID()}.tmp`;
    await fs.copyFile(output, staging);
    await fs.rename(staging, dest);
    await atomic(`${dest}.json`, {
      duration: Number(info.format.duration),
      frames: frames.length,
      speech: result.speech.map((s) => ({
        actionId: s.actionId,
        offset: (s.epoch - start) / 1000,
        duration: durations[s.actionId],
      })),
      createdAt: Date.now(),
    });
  } catch (error) {
    const debug = path.join(root, plan.id, 'debug');
    await fs.mkdir(debug, { recursive: true });
    await page?.screenshot({ path: path.join(debug, `${clip.key}.png`) }).catch(() => {});
    throw error;
  } finally {
    await browser?.close();
    await Promise.allSettled(writes);
    await fs.rm(temp, { recursive: true, force: true });
  }
}
async function pump() {
  if (active) return;
  active = true;
  while (queue.length) {
    const job = queue.shift(),
      key = `${job.id}:${job.version}`;
    const statusFile = path.join(root, job.id, 'jobs', `${job.version}.json`);
    let plan,
      completed = 0;
    const status = (state, extra = {}) =>
      atomic(statusFile, {
        version: job.version,
        state,
        completed,
        total: plan?.clips.length || 0,
        updatedAt: Date.now(),
        ...extra,
      });
    try {
      plan = JSON.parse(
        await fs.readFile(path.join(root, job.id, 'versions', `${job.version}.json`), 'utf8'),
      );
      for (const clip of plan.clips) {
        if (!safeHash(clip.key) || !safeId(clip.sceneId)) throw new Error('Invalid video clip');
        if (
          !(await fs.stat(path.join(root, plan.id, 'clips', `${clip.key}.mp4`)).catch(() => null))
            ?.size
        ) {
          await status('rendering', { currentSceneId: clip.sceneId, phase: 'loading' });
          await capture(job, plan, clip, phase => status('rendering', { currentSceneId: clip.sceneId, phase }));
        }
        completed++;
        await status('rendering');
      }
      await status('ready');
    } catch (e) {
      await status('failed', { error: String(e.message || e).slice(0, 800) });
      console.error('video render failed', job.id, e.name);
    } finally {
      jobs.delete(key);
    }
  }
  active = false;
}
// A container restart keeps completed MP4s but cannot keep a browser session.
// Surface interrupted jobs as retryable instead of polling "rendering" forever.
for (const id of await fs.readdir(root).catch(() => [])) {
  if (!safeId(id)) continue;
  const dir = path.join(root, id, 'jobs');
  for (const name of await fs.readdir(dir).catch(() => [])) {
    if (!/^[a-f0-9]{64}\.json$/.test(name)) continue;
    const file = path.join(dir, name);
    const status = JSON.parse(await fs.readFile(file, 'utf8'));
    if (['queued', 'rendering'].includes(status.state))
      await atomic(file, {
        ...status,
        state: 'failed',
        error: '视频服务已重新启动，请重试未完成视频',
        updatedAt: Date.now(),
      });
  }
}
http
  .createServer(async (req, res) => {
    if (req.url === '/health' && req.method === 'GET')
      return reply(res, 200, { success: true, active, queued: queue.length });
    if (req.url !== '/jobs' || req.method !== 'POST' || !equal(req.headers['x-video-worker-key']))
      return reply(res, 403, { error: 'Forbidden' });
    try {
      let raw = '';
      for await (const chunk of req) {
        raw += chunk;
        if (raw.length > 5000) throw new Error('Too large');
      }
      const job = JSON.parse(raw);
      if (
        !safeId(job.id) ||
        !safeHash(job.version) ||
        typeof job.grant !== 'string' ||
        job.grant.length > 600 ||
        job.origin !== origin
      )
        throw new Error('Invalid job');
      const key = `${job.id}:${job.version}`;
      if (!jobs.has(key)) {
        if (jobs.size >= 10) return reply(res, 429, { error: 'Queue full' });
        await fs.access(path.join(root, job.id, 'versions', `${job.version}.json`));
        await atomic(path.join(root, job.id, 'jobs', `${job.version}.json`), {
          version: job.version,
          state: 'queued',
          completed: 0,
          total: 0,
          updatedAt: Date.now(),
        });
        jobs.set(key, job);
        queue.push(job);
        void pump();
      }
      reply(res, 202, { accepted: true });
    } catch {
      reply(res, 400, { error: 'Invalid job' });
    }
  })
  .listen(Number(process.env.PORT || 9010), '0.0.0.0');
