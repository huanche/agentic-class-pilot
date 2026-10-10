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
    // Legacy boolean attribute alongside the allow list — Safari and older
    // engines only grant iframe fullscreen through allowfullscreen.
    iframe.setAttribute("allowfullscreen", "true");
    iframe.referrerPolicy = "same-origin";
    iframe.style.width = "100%";
    // Match the host slot: a taller iframe was clipped by its 16:9 parent,
    // hiding the embedded player's bottom controls and trapping scroll.
    iframe.style.height = "100%";
    iframe.style.minHeight = "0";
    iframe.style.border = "0";
    iframe.style.borderRadius = "16px";
    iframe.style.background = "#fff";

    let ended = false;
    function receive(event) {
      if (event.origin !== playerOrigin || event.source !== iframe.contentWindow) return;
      const message = playerMessage(event.data);
      if (!message) return;
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
      window.removeEventListener("message", receive);
      iframe.remove();
    };
  },
};
