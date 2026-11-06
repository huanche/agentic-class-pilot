/* Platform player adapter.
   Embeds the single teacher-side player implementation and translates its
   postMessage protocol into the student Agent's stable onEnded callback. */

function playerMessage(data) {
  if (!data || typeof data !== "object") return null;
  if (data.source === "teacher-workspace" && data.payload && typeof data.payload === "object") {
    return { type: data.type, ...data.payload };
  }
  return data;
}

export const platformPlayerAdapter = {
  mount(container, context) {
    const url = context.lesson && context.lesson.playerUrl;
    if (!url) throw new Error("课程没有可播放的已发布课堂地址");

    const playerOrigin = new URL(url, window.location.href).origin;
    const embedUrl = new URL(url, window.location.href);
    embedUrl.searchParams.set("embedded", "player");
    if (context.replay) embedUrl.searchParams.set("replay", "1");
    const iframe = document.createElement("iframe");
    iframe.src = embedUrl;
    iframe.title = "课程播放器";
    iframe.allow = "autoplay; fullscreen";
    // Legacy boolean attribute alongside the allow list — Safari and older
    // engines only grant iframe fullscreen through allowfullscreen.
    iframe.setAttribute("allowfullscreen", "true");
    iframe.referrerPolicy = "same-origin";
    iframe.style.width = "100%";
    iframe.style.height = "100%";
    iframe.style.minHeight = "0";
    iframe.style.border = "0";
    iframe.style.background = "#fff";

    let ended = false;
    // 握手超时：教师端播放器挂载后会立即发 PLAYER_READY。开发服务器冷编译
    // 或大课堂时首帧可能超过 20 秒——超时只给提示，播放器随后就绪会自动清除；
    // 若 iframe 根本没加载（授权失败、跳登录页），提示会一直保留。
    let ready = false;
    const HANDSHAKE_TIMEOUT_MS = 20000;
    const handshakeTimer = setTimeout(() => {
      if (!ready && context.onError) {
        const slow = new Error("播放器仍在加载（教师端响应较慢）。如长时间未出画面请刷新重试。");
        slow.slowLoad = true;
        context.onError(slow);
      }
    }, HANDSHAKE_TIMEOUT_MS);

    function receive(event) {
      if (event.origin !== playerOrigin || event.source !== iframe.contentWindow) return;
      const message = playerMessage(event.data);
      if (!message) return;
      if (message.type === "PLAYER_LAYOUT") {
        if (Number.isInteger(message.height) && message.height >= 120 && message.height <= 4096) {
          iframe.style.height = `${message.height}px`;
          container.dataset.playerSized = "true";
        }
        return;
      }
      if (!ready && ["PLAYER_READY", "SCENE_COMPLETED", "PLAYBACK_ENDED", "CLASSROOM_COMPLETED"].includes(message.type)) {
        ready = true;
        clearTimeout(handshakeTimer);
        if (context.onReady) context.onReady();
      }
      if (message.type === "SCENE_COMPLETED" && context.onSceneCompleted) {
        context.onSceneCompleted(message.sceneId, message.eventId);
      } else if ((message.type === "PLAYBACK_ENDED" || message.type === "CLASSROOM_COMPLETED") && !ended) {
        ended = true;
        // Only the whole-playback event advances the student learning phase.
        context.onEnded(message.sceneId, message.eventId);
      } else if (message.type === "PLAYER_ERROR" && context.onError) {
        context.onError(new Error(message.message || "播放器运行失败"));
      }
    }

    window.addEventListener("message", receive);
    container.replaceChildren(iframe);
    return function destroy() {
      clearTimeout(handshakeTimer);
      window.removeEventListener("message", receive);
      iframe.remove();
      delete container.dataset.playerSized;
    };
  },
};
