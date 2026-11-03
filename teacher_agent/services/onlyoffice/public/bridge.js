/* The only callable editor methods are this fixed read-only playback allowlist. */
(() => {
  const nonce = /\/plugin\/session\/([A-Za-z0-9_-]{32})\/index\.html$/.exec(location.pathname)?.[1];
  const parent = window.parent.parent,
    channel = 'agentic-onlyoffice-bridge-v1';
  const methods = {
    start: 'StartSlideShow',
    end: 'EndSlideShow',
    advance: 'GoToNextSlideInSlideShow',
    pause: 'PauseSlideShow',
    resume: 'ResumeSlideShow',
    goto: 'GoToSlideInSlideShow',
  };
  const emit = (event, data = {}) =>
    parent.postMessage({ channel, nonce, event, ...data }, location.origin);
  if (!nonce || !window.Asc?.plugin) return;
  window.Asc.plugin.init = () => {
    for (const name of ['onSlideShowBegin', 'onSlideShowEnd', 'onSlideShowSlideChanged'])
      window.Asc.plugin.attachEditorEvent(name, (data) => emit(name, { data }));
    emit('ready');
  };
  window.Asc.plugin.button = () => {};
  addEventListener('message', (event) => {
    const m = event.data;
    if (
      event.origin !== location.origin ||
      event.source !== parent ||
      m?.channel !== channel ||
      m.nonce !== nonce ||
      !Number.isSafeInteger(m.id) ||
      !Object.hasOwn(methods, m.command)
    )
      return;
    if (m.command === 'goto' && (!Number.isSafeInteger(m.page) || m.page < 1 || m.page > 2000))
      return;
    try {
      window.Asc.plugin.executeMethod(
        methods[m.command],
        m.command === 'goto' ? [m.page] : [],
        () => emit('ack', { id: m.id }),
      );
    } catch (e) {
      emit('error', { id: m.id, detail: String(e.message || e) });
    }
  });
})();
