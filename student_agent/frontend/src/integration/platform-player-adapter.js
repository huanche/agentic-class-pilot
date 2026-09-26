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
    // ?embedded=player = player-only mode: the embedded classroom player hides
    // its chrome (header, scene sidebar, AI-teacher roundtable, chat panel) and
    // shows just the scene canvas.
    const embedUrl = url + (url.includes("?") ? "&" : "?") + "embedded=player" + (context.replay ? "&replay=1" : "");
    const iframe = document.createElement("iframe");
    iframe.src = embedUrl;
    iframe.title = "课程播放器";
    iframe.allow = "autoplay; fullscreen";
    iframe.referrerPolicy = "same-origin";
    iframe.style.width = "100%";
    iframe.style.height = "min(72vh, 760px)";
    iframe.style.minHeight = "480px";
    iframe.style.border = "0";
    iframe.style.borderRadius = "16px";
    iframe.style.background = "#fff";

    let ended = false;
    function receive(event) {
      if (event.origin !== playerOrigin || event.source !== iframe.contentWindow) return;
      const message = playerMessage(event.data);
      if (!message) return;
      if ((message.type === "PLAYBACK_ENDED" || message.type === "CLASSROOM_COMPLETED") && !ended) {
        ended = true;
        // 透传场景/事件 id：平台侧按场景幂等记进度，适配器边界丢了这个信息就补不回来
        context.onEnded(message.sceneId, message.eventId);
      } else if (message.type === "PLAYER_ERROR" && context.onError) {
        context.onError(new Error(message.message || "播放器运行失败"));
      }
    }

    window.addEventListener("message", receive);
    container.replaceChildren(iframe);
    return function destroy() {
      window.removeEventListener("message", receive);
      iframe.remove();
    };
  },
};
