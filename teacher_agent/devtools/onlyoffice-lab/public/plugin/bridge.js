import { CHANNEL, validCommand, validPeerMessage } from '../protocol.mjs';

// ONLYOFFICE appends language/theme query parameters to variation URLs.
const nonce = /\/plugin\/session\/([A-Za-z0-9_-]{32})\/index\.html$/.exec(location.pathname)?.[1];
const origin = location.origin;
// The plugin is inside the editor iframe; its grandparent is the owning player.
// window.top may belong to a surrounding workspace/browser embedding surface.
const parent = window.parent.parent;
const methods = {
  start: 'StartSlideShow',
  end: 'EndSlideShow',
  advance: 'GoToNextSlideInSlideShow',
  pause: 'PauseSlideShow',
  resume: 'ResumeSlideShow',
  goto: 'GoToSlideInSlideShow',
};
function emit(event, data = {}) {
  parent.postMessage({ channel: CHANNEL, nonce, event, at: Date.now(), ...data }, origin);
}

if (!window.Asc?.plugin) {
  emit('bridge-error', { detail: 'ONLYOFFICE 插件接口未加载。' });
} else {
  emit('bridge-loaded');
  window.Asc.plugin.init = function () {
    for (const event of [
      'onSlideShowBegin',
      'onSlideShowEnd',
      'onSlideShowSlideChanged',
      'onSlideShowNextSlide',
    ]) {
      window.Asc.plugin.attachEditorEvent(event, (data) => emit(event, { data }));
    }
    emit('ready');
  };
  window.Asc.plugin.button = function () {};
  window.addEventListener('message', (event) => {
    if (!validPeerMessage(event, origin, nonce, parent) || !validCommand(event.data)) return;
    const message = event.data;
    try {
      window.Asc.plugin.executeMethod(
        methods[message.command],
        message.command === 'goto' ? [message.page] : [],
        () => emit('ack', { id: message.id, command: message.command }),
      );
    } catch (error) {
      emit('command-error', { id: message.id, detail: String(error?.message || error) });
    }
  });
}
