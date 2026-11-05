import { CHANNEL, validPeerMessage } from './protocol.mjs';

const $ = (id) => document.getElementById(id);
const prefix = '/onlyoffice-test';
let token = new URLSearchParams(location.hash.slice(1)).get('access');
if (token) {
  sessionStorage.setItem('onlyoffice-lab-access', token);
  history.replaceState(null, '', location.pathname);
} else token = sessionStorage.getItem('onlyoffice-lab-access');
const authHeaders = token ? { Authorization: `Bearer ${token}` } : {};
const events = [];
const pending = new Map();
const waiters = new Map();
const audioUrls = new Map();
const audioLoads = new Map();
let sample,
  nonce,
  peer,
  editor,
  requestId = 0,
  page = 0,
  cue = 0,
  run = 0;
let ready = false,
  running = false,
  paused = false,
  showing = false,
  resetting = false;
let audio, resolveAudio, resumeWaiter;
let pauseStarted = 0,
  pausedTotal = 0;

function log(event, detail = '') {
  events.push({ event, detail, page: page + 1, cue, at: Date.now() });
  $('events').textContent = events
    .slice(-25)
    .map(
      (e) =>
        `${new Date(e.at).toLocaleTimeString()}  ${e.event}  第${e.page}页 / 步骤${e.cue}  ${e.detail}`,
    )
    .join('\n');
}
function error(message) {
  $('error').hidden = false;
  $('error').textContent = message;
  log('error', message);
}
function render() {
  $('position').textContent =
    `第 ${page + 1} / 5 页 · 原稿第 ${sample?.pages[page]?.originalPage || 5} 页`;
  $('cue-status').textContent = ready
    ? `动画步骤 ${cue} / ${sample.pages[page].cues.length}${paused ? ' · 已暂停' : ''}`
    : '放映接口连接中';
  $('play').disabled = !ready || running;
  $('pause').disabled = !running;
  $('pause').textContent = paused ? '继续' : '暂停';
  $('stop').disabled = !running;
  $('advance').disabled = !ready || running;
  $('final').disabled = !ready || running;
  for (const button of $('pages').children) {
    button.disabled = !ready || running;
    button.setAttribute('aria-current', Number(button.dataset.page) === page ? 'page' : 'false');
  }
}
async function api(path, options = {}) {
  const response = await fetch(prefix + path, {
    ...options,
    headers: { ...authHeaders, ...options.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || `请求失败：HTTP ${response.status}`);
  }
  return response;
}
function command(name, extra = {}) {
  if (!peer) return Promise.reject(new Error('放映插件尚未连接'));
  const id = ++requestId;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`放映命令超时：${name}`));
    }, 12000);
    pending.set(id, {
      resolve: () => {
        clearTimeout(timer);
        resolve();
      },
      reject,
    });
    peer.postMessage({ channel: CHANNEL, nonce, id, command: name, ...extra }, location.origin);
  });
}
function waitEvent(name, timeout = 12000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      waiters.delete(name);
      reject(new Error(`等待放映状态超时：${name}`));
    }, timeout);
    waiters.set(name, () => {
      clearTimeout(timer);
      resolve();
    });
  });
}
window.addEventListener('message', (event) => {
  if (!nonce || !validPeerMessage(event, location.origin, nonce, peer)) return;
  const message = event.data;
  if (message.event === 'ready') {
    peer = event.source;
    ready = true;
    $('status').textContent = '原稿与配音控制已连接';
    render();
    log('bridge-ready');
  } else if (message.event === 'ack') {
    pending.get(message.id)?.resolve();
    pending.delete(message.id);
  } else if (message.event === 'command-error' || message.event === 'bridge-error') {
    pending.get(message.id)?.reject(new Error(message.detail));
    pending.delete(message.id);
    error(message.detail);
  } else {
    if (message.event === 'onSlideShowBegin') showing = true;
    if (message.event === 'onSlideShowEnd') {
      showing = false;
      if (running && !resetting) stop();
    }
    if (message.event === 'onSlideShowSlideChanged') {
      // SlideChanged reports zero-based indices; GoToSlide accepts one-based numbers.
      const index = message.data?.slideIndex;
      if (Number.isInteger(index) && index >= 0 && index < 5) {
        if (running && !resetting && index !== page) stop();
        page = index;
        cue = 0;
        render();
      }
    }
    waiters.get(message.event)?.();
    waiters.delete(message.event);
    log(message.event, JSON.stringify(message.data || {}));
  }
});

async function resetPage(target) {
  resetting = true;
  try {
    if (showing) await command('end');
    const began = waitEvent('onSlideShowBegin');
    await command('start');
    await began;
    // StartSlideShow may start at the editor's selected slide. Always select the
    // requested page explicitly. No change event is emitted if it is already there.
    await command('goto', { page: target + 1 });
    await settleTransition(target);
    page = target;
    cue = 0;
    render();
  } finally {
    resetting = false;
  }
}
async function settleTransition(target) {
  // Native navigation acknowledges before its transition finishes. A click in
  // that interval completes the transition instead of starting an object effect.
  await new Promise((resolve) =>
    setTimeout(resolve, (sample.pages[target].transitionDurationMs ?? 1200) + 150),
  );
  log('transition-settled');
}
async function getAudio(name) {
  if (audioUrls.has(name)) return audioUrls.get(name);
  if (!audioLoads.has(name)) {
    const load = api(`/api/audio/${name}`)
      .then((response) => response.blob())
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        audioUrls.set(name, url);
        return url;
      })
      .catch((error) => {
        audioLoads.delete(name);
        throw error;
      });
    audioLoads.set(name, load);
  }
  return audioLoads.get(name);
}
function prefetchAudio(p, c) {
  const upcoming = sample.pages.slice(p).flatMap((item, i) => (i ? item.cues : item.cues.slice(c)));
  for (const item of upcoming.slice(0, 3)) void getAudio(item.audio).catch(() => {});
}
function stop() {
  run++;
  running = false;
  paused = false;
  audio?.pause();
  resolveAudio?.();
  resolveAudio = undefined;
  resumeWaiter?.();
  resumeWaiter = undefined;
  if (showing) void command('pause').catch(() => {});
  log('stopped');
  render();
}
async function hold() {
  if (paused)
    await new Promise((resolve) => {
      resumeWaiter = resolve;
    });
}
async function play() {
  $('error').hidden = true;
  const target = page;
  try {
    await resetPage(target);
    running = true;
    paused = false;
    const version = ++run;
    render();
    for (let p = target; p < 5 && version === run; p++) {
      if (p !== page) {
        const changed = waitEvent('onSlideShowSlideChanged');
        page = p;
        await command('goto', { page: p + 1 });
        await changed;
        await settleTransition(p);
      }
      for (let c = 0; c < sample.pages[p].cues.length && version === run; c++) {
        await hold();
        if (version !== run) return;
        const item = sample.pages[p].cues[c];
        prefetchAudio(p, c);
        const url = await getAudio(item.audio);
        await hold();
        if (version !== run) return;
        cue = c + 1;
        $('speech').textContent = item.text;
        render();
        audio = new Audio(url);
        const clip = audio;
        audio.preload = 'auto';
        $('audio-player').replaceChildren(audio);
        audio.addEventListener('timeupdate', () => {
          $('audio-clock').textContent =
            `本段配音 ${clip.currentTime.toFixed(1)} / ${Number.isFinite(clip.duration) ? clip.duration.toFixed(1) : '—'} 秒`;
        });
        audio.addEventListener('pause', () => {
          // Browsers/media sessions can pause audio independently of our button.
          if (version !== run || !running || paused || clip.ended) return;
          paused = true;
          pauseStarted = Date.now();
          log(
            'media-paused',
            `本段 ${clip.currentTime.toFixed(2)} 秒；页面${document.hidden ? '在后台' : '可见'}`,
          );
          render();
          void command('pause').catch((e) => error(e.message));
        });
        const ended = new Promise((resolve, reject) => {
          resolveAudio = resolve;
          audio.addEventListener('ended', resolve, { once: true });
          audio.addEventListener('error', () => reject(new Error('配音加载失败')), { once: true });
        });
        const started = Date.now();
        const pauseBaseline = pausedTotal;
        log('animation-request', item.effectSummary);
        await command('advance');
        if (version !== run) return;
        audio.addEventListener(
          'playing',
          () => log('audio-playing', `距动画请求 ${Date.now() - started} ms`),
          { once: true },
        );
        await hold();
        if (version !== run) return;
        await audio.play();
        await ended;
        if (version !== run) return;
        log('audio-ended', `${audio.duration.toFixed(2)} 秒`);
        // The next click never overtakes an unfinished native animation group.
        while (
          Date.now() -
            started -
            (pausedTotal - pauseBaseline) -
            (paused ? Date.now() - pauseStarted : 0) <
            item.durationMs &&
          version === run
        ) {
          await hold();
          await new Promise((resolve) => setTimeout(resolve, 50));
        }
      }
    }
    if (version === run) {
      running = false;
      paused = false;
      $('status').textContent = '5 页放映与配音已播放完成';
      log('playback-complete');
      render();
    }
  } catch (e) {
    stop();
    error(e.message);
  }
}
$('play').addEventListener('click', play);
$('stop').addEventListener('click', stop);
$('pause').addEventListener('click', async () => {
  if (!running) return;
  try {
    if (!paused) {
      paused = true;
      pauseStarted = Date.now();
      audio?.pause();
      await command('pause');
      log('paused');
    } else {
      await command('resume');
      pausedTotal += Date.now() - pauseStarted;
      paused = false;
      if (audio && !audio.ended) await audio.play();
      resumeWaiter?.();
      resumeWaiter = undefined;
      log('resumed');
    }
    render();
  } catch (e) {
    stop();
    error(e.message);
  }
});
$('advance').addEventListener('click', async () => {
  try {
    if (!showing) await resetPage(page);
    if (cue >= sample.pages[page].cues.length) return;
    await command('advance');
    cue++;
    render();
    log('manual-advance');
  } catch (e) {
    error(e.message);
  }
});
$('final').addEventListener('click', async () => {
  const target = page;
  const version = ++run;
  try {
    running = true;
    render();
    await resetPage(target);
    running = true;
    for (const item of sample.pages[target].cues) {
      await hold();
      if (version !== run) return;
      await command('advance');
      cue++;
      render();
      await new Promise((resolve) => setTimeout(resolve, Math.max(80, item.durationMs)));
    }
    log('final-layout');
  } catch (e) {
    error(e.message);
  } finally {
    running = false;
    render();
  }
});
$('download').addEventListener('click', () => {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify({ source: sample?.sourceSha256, events }, null, 2)], {
      type: 'application/json',
    }),
  );
  const a = document.createElement('a');
  a.href = url;
  a.download = 'onlyoffice-playback.json';
  a.click();
  URL.revokeObjectURL(url);
});
setInterval(() => {
  if (events.length)
    void api('/api/telemetry', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ events: events.slice(-100) }),
    }).catch(() => {});
}, 30000);

try {
  const data = await (await api('/api/config')).json();
  nonce = data.nonce;
  sample = data.sample;
  prefetchAudio(0, 0);
  for (let p = 0; p < 5; p++) {
    const button = document.createElement('button');
    button.dataset.page = p;
    button.textContent = `${p + 1}. ${sample.pages[p].title}`;
    button.addEventListener('click', async () => {
      try {
        await resetPage(p);
      } catch (e) {
        error(e.message);
      }
    });
    $('pages').append(button);
  }
  render();
  await new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = data.engineUrl;
    script.onload = resolve;
    script.onerror = () => reject(new Error('ONLYOFFICE 放映服务未连接'));
    document.head.append(script);
  });
  editor = new window.DocsAPI.DocEditor('editor', {
    ...data.editor,
    events: {
      onDocumentReady: () => {
        log('document-ready');
        $('status').textContent = ready ? '原稿与配音控制已连接' : '原稿已加载，正在连接配音控制…';
      },
      onError: (event) =>
        error(`ONLYOFFICE：${event.data?.errorDescription || event.data?.errorCode || '加载失败'}`),
    },
  });
  setTimeout(() => {
    if (!ready) error('放映插件尚未连接，暂不能验证自动动画与配音同步。');
  }, 45000);
} catch (e) {
  error(e.message);
  $('status').textContent = '尚未就绪';
}
