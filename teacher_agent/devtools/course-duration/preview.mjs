import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
const { build } = createRequire(require.resolve('tsx/package.json'))('esbuild');
const teacher = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'course-duration-'));
const fixturesDir =
  process.env.COURSE_DURATION_FIXTURES || path.resolve(teacher, '../outputs/playback-diagnostics');
const alias = { '@': teacher };
await build({
  entryPoints: [path.join(teacher, 'devtools/course-duration/preview.tsx')],
  outfile: path.join(temporary, 'preview.js'),
  bundle: true,
  platform: 'browser',
  jsx: 'automatic',
  alias,
  minify: true,
  define: { 'process.env.NODE_ENV': '"production"' },
});
await build({
  stdin: {
    contents: `export * from './lib/generation/course-duration'; export { measureAudioDuration } from './lib/audio/audio-duration';`,
    resolveDir: teacher,
    loader: 'ts',
  },
  outfile: path.join(temporary, 'measurement.mjs'),
  bundle: true,
  platform: 'node',
  format: 'esm',
  alias,
});
const { measureAudioDuration, measureScenePlaybackSeconds, durationMeasurementKey } = await import(
  pathToFileURL(path.join(temporary, 'measurement.mjs')).href
);
const fixtures = [];
for (const number of [1, 2]) {
  const filename = path.join(fixturesDir, `course-${number}.original.json`);
  let manifest;
  try {
    manifest = JSON.parse(await fs.readFile(filename, 'utf8'));
  } catch (error) {
    if (error.code === 'ENOENT') continue;
    throw error;
  }
  const durations = {};
  let audioSeconds = 0;
  let audioClips = 0;
  for (const reference of Object.keys(manifest.mediaIndex ?? {})) {
    if (!/^audio\/[A-Za-z0-9_.-]+\.(wav|mp3)$/.test(reference)) continue;
    try {
      const bytes = await fs.readFile(path.join(fixturesDir, `course-${number}-assets`, reference));
      const seconds = measureAudioDuration(bytes, path.extname(reference).slice(1));
      if (seconds != null) {
        durations[reference] = seconds;
        audioSeconds += seconds;
        audioClips++;
      }
    } catch {
      /* Incomplete local exports remain explicitly unmeasured. */
    }
  }
  for (const scene of manifest.scenes) {
    const byAction = Object.fromEntries(
      (scene.actions ?? [])
        .filter((action) => action.type === 'speech')
        .map((action) => [action.id, durations[action.audioRef]]),
    );
    scene.timing = {
      measuredDurationSec: measureScenePlaybackSeconds(scene, byAction),
      measurementKey: durationMeasurementKey(scene),
    };
  }
  fixtures.push({ name: manifest.stage.name, scenes: manifest.scenes, audioSeconds, audioClips });
}
const html = `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>课件时长本地测试</title><style>
body{margin:0;background:#f4f5fa;color:#253652;font:16px/1.6 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1000px;margin:36px auto;padding:0 24px}h1{font-size:28px}h2{font-size:20px}section{background:white;border:1px solid #e4e6ef;border-radius:16px;padding:24px;margin:20px 0}input,select,button{font:inherit;border:1px solid #c9cedd;border-radius:8px;padding:8px 12px;background:white;color:inherit}input{width:110px}button{cursor:pointer}button:hover{border-color:#7955d9;color:#6942c5}.buttons{display:flex;gap:12px;margin-top:16px}p{color:#61708a}pre{max-height:400px;overflow:auto;font-size:13px;background:#f7f8fc;padding:16px;border-radius:10px}select{max-width:100%}[aria-invalid=true]{border-color:#dc2626}section>span{display:block;padding:12px;background:#f2edff;border-radius:8px;color:#6942c5}
</style><div id="root"></div><script src="/preview.js"></script></html>`;
const port = Number(process.env.COURSE_DURATION_PREVIEW_PORT || 3214);
http
  .createServer(async (request, response) => {
    const route = new URL(request.url, 'http://localhost').pathname;
    if (route === '/') {
      response.setHeader('Content-Type', 'text/html; charset=utf-8');
      response.end(html);
    } else if (route === '/fixtures') {
      response.setHeader('Content-Type', 'application/json; charset=utf-8');
      response.end(JSON.stringify(fixtures));
    } else if (route === '/preview.js') {
      response.setHeader('Content-Type', 'application/javascript');
      response.end(await fs.readFile(path.join(temporary, 'preview.js')));
    } else {
      response.writeHead(404);
      response.end();
    }
  })
  .listen(port, '127.0.0.1', () =>
    console.log(
      `无需 API Key 的时长测试：http://127.0.0.1:${port}（原始课件 ${fixtures.length} 份）`,
    ),
  );
