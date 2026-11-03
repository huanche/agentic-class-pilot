const channel = 'agentic-native-pptx-v1',
  bridge = 'agentic-onlyoffice-bridge-v1';
const query = new URLSearchParams(location.search),
  sceneId = query.get('scene');
const pending = new Map(),
  waiters = new Map();
let peer,
  config,
  request = 0,
  cursor = 0,
  showing = false,
  paused = false,
  documentReady = false,
  initializing = false,
  initialized = false,
  version = 0,
  queue = Promise.resolve();
const emit = (event, data = {}) =>
  parent.postMessage({ channel, sceneId, event, ...data }, location.origin);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const command = (command, page) =>
  new Promise((resolve, reject) => {
    const id = ++request,
      timer = setTimeout(() => {
        pending.delete(id);
        reject(new Error('原稿引擎未响应'));
      }, 12000);
    pending.set(id, {
      resolve: () => {
        clearTimeout(timer);
        resolve();
      },
      reject,
    });
    peer.postMessage({ channel: bridge, nonce: config.nonce, id, command, page }, location.origin);
  });
const waitEvent = (name) =>
  new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      waiters.delete(name);
      reject(new Error('原稿放映状态超时'));
    }, 12000);
    waiters.set(name, () => {
      clearTimeout(timer);
      resolve();
    });
  });
async function reset() {
  if (showing) await command('end');
  const began = waitEvent('onSlideShowBegin');
  await command('start');
  await began;
  await command('goto', config.page);
  // A click during a native page transition is otherwise consumed by that transition.
  await sleep(Math.max(1400, config.transitionMs || 0));
  cursor = 0;
  paused = false;
}
async function initializeWhenReady() {
  if (!documentReady || !peer || initializing || initialized) return;
  initializing = true;
  try {
    await reset();
    initialized = true;
    document.getElementById('status').hidden = true;
    emit('ready');
  } catch (e) {
    document.getElementById('status').textContent = e.message;
    emit('error', { detail: e.message });
  } finally {
    initializing = false;
  }
}
async function seek(step) {
  if (!Number.isSafeInteger(step) || step < 0 || step > config.steps.length)
    throw new Error('原稿动画步骤越界');
  if (step < cursor) await reset();
  const run = version;
  while (cursor < step) {
    if (run !== version) throw new Error('播放已停止');
    while (paused) {
      await sleep(40);
      if (run !== version) throw new Error('播放已停止');
    }
    const duration = config.steps[cursor];
    await command('advance');
    cursor++;
    let elapsed = 0,
      last = performance.now();
    while (elapsed < duration) {
      await sleep(20);
      const now = performance.now();
      if (!paused) elapsed += now - last;
      last = now;
      if (run !== version) throw new Error('播放已停止');
    }
  }
}
addEventListener('message', (event) => {
  const m = event.data;
  if (event.origin !== location.origin || !m) return;
  if (m.channel === bridge && m.nonce === config?.nonce && (!peer || event.source === peer)) {
    if (m.event === 'ready') {
      peer = event.source;
      void initializeWhenReady();
    }
    if (m.event === 'onSlideShowBegin') showing = true;
    if (m.event === 'onSlideShowEnd') showing = false;
    if (m.event === 'ack') {
      pending.get(m.id)?.resolve();
      pending.delete(m.id);
    }
    if (m.event === 'error') {
      pending.get(m.id)?.reject(new Error(m.detail));
      pending.delete(m.id);
    }
    waiters.get(m.event)?.();
    waiters.delete(m.event);
    return;
  }
  if (
    event.source !== parent ||
    m.channel !== channel ||
    m.sceneId !== sceneId ||
    !Number.isSafeInteger(m.id) ||
    !['seek', 'reset', 'pause', 'resume'].includes(m.command)
  )
    return;
  const execute = async () => {
    if (!peer) throw new Error('原稿尚未连接');
    if (m.command === 'seek') await seek(m.step);
    else if (m.command === 'reset') await reset();
    else {
      paused = m.command === 'pause';
      await command(m.command);
    }
    emit('ack', { id: m.id });
  };
  if (m.command === 'reset') version++;
  if (['pause', 'resume'].includes(m.command))
    void execute().catch((e) => emit('error', { id: m.id, detail: e.message }));
  else
    queue = queue
      .catch(() => {})
      .then(execute)
      .catch((e) =>
        emit(e.message === '播放已停止' ? 'ack' : 'error', { id: m.id, detail: e.message }),
      );
});
try {
  const response = await fetch(
    `/onlyoffice/api/config?classroom=${encodeURIComponent(query.get('classroom') || '')}&scene=${encodeURIComponent(sceneId || '')}`,
  );
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || '原稿加载失败');
  config = body;
  await new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = config.engineUrl;
    script.onload = resolve;
    script.onerror = () => reject(new Error('原稿引擎脚本加载失败'));
    document.head.append(script);
  });
  new DocsAPI.DocEditor('editor', {
    ...config.editor,
    events: {
      onDocumentReady: () => {
        documentReady = true;
        void initializeWhenReady();
      },
      onError: (event) =>
        emit('error', { detail: event?.data?.errorDescription || '原稿引擎错误' }),
    },
  });
} catch (e) {
  document.getElementById('status').textContent = e.message;
  emit('error', { detail: e.message });
}
