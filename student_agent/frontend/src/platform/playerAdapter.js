/* Platform player adapter: embeds the teacher-side classroom player and
 * bridges its postMessage events to the student agent's media_done flow.
 *
 * Registration contract (see video-player.js):
 *   window.StudentAgentVideoPlayerBridge.register(adapter)
 * adapter.mount(container, context) — context.onEnded() must fire when the
 * lesson media completes.
 *
 * Message protocol (teacher-side player-host-events.ts):
 *   SCENE_COMPLETED { classroomId, sceneId, eventId }
 *   PLAYBACK_ENDED  { classroomId, sceneId, eventId }
 * Events are validated against the expected classroomId and deduplicated by
 * eventId (see apps/integration/player_bridge.py for the backend contract).
 */

/* global window, document */

var platformPlayer = {
  expectedClassroomId: null,
  seenEventIds: {},
  completedScenes: {},
  ended: false,
  iframe: null,
  container: null,
  onMediaDone: null,
  messageHandler: null,

  mount: function (container, context) {
    var self = this;
    self.container = container;
    self.onMediaDone = context && context.onEnded;

    var classroomId = (context && context.classroomId) ||
      (window.__studentPlatformContext && window.__studentPlatformContext.classroomId);

    if (!classroomId) {
      container.textContent = "本课时尚未发布播放器内容";
      return { destroy: function () { self.destroy(); } };
    }

    self.expectedClassroomId = classroomId;
    self.seenEventIds = {};
    self.completedScenes = {};
    self.ended = false;

    // Resolve the player URL: same origin, teacher prefix (Caddy strips it).
    // ?embedded=player = player-only mode: the embedded classroom player hides
    // its chrome (header, scene sidebar, AI-teacher roundtable, chat panel) and
    // shows just the scene canvas.
    var iframe = document.createElement("iframe");
    iframe.src = "/teacher/classroom-player/" + encodeURIComponent(classroomId) + "?embedded=player" + (context && context.replay ? "&replay=1" : "");
    iframe.style.width = "100%";
    iframe.style.height = "100%";
    iframe.style.border = "none";
    iframe.setAttribute("allowfullscreen", "true");
    // Let the embedded teacher player start audio without a direct click
    // inside the iframe (browsers block play() in iframes without this).
    iframe.setAttribute("allow", "autoplay; encrypted-media");
    iframe.setAttribute("title", "课程播放器");

    var status = document.getElementById("video-player-status");
    iframe.addEventListener("load", function () {
      if (status) status.textContent = "播放器已加载，正在播放课程内容…";
    });
    iframe.addEventListener("error", function () {
      if (status) status.textContent = "播放器加载失败，请刷新重试";
    });

    container.replaceChildren(iframe);
    self.iframe = iframe;

    if (!self.messageHandler) {
      self.messageHandler = function (event) { self.handleMessage(event); };
      window.addEventListener("message", self.messageHandler);
    }

    return {
      destroy: function () { self.destroy(); }
    };
  },

  handleMessage: function (event) {
    if (event.origin !== window.location.origin) return;
    var data = event.data;
    if (!data || typeof data !== "object") return;
    var type = data.type;
    if (type !== "SCENE_COMPLETED" && type !== "PLAYBACK_ENDED" && type !== "PLAYER_READY") return;
    if (data.classroomId && data.classroomId !== this.expectedClassroomId) return;
    if (data.eventId) {
      if (this.seenEventIds[data.eventId]) return;
      this.seenEventIds[data.eventId] = true;
    }

    var status = document.getElementById("video-player-status");

    if (type === "SCENE_COMPLETED" && data.sceneId && !this.completedScenes[data.sceneId]) {
      this.completedScenes[data.sceneId] = true;
      // 带上场景/事件 id —— 平台侧按场景幂等记进度，丢了就退化成"整段完成"一行
      if (this.onMediaDone) this.onMediaDone(data.sceneId, data.eventId);
    }
    if (type === "PLAYBACK_ENDED" && !this.ended) {
      this.ended = true;
      if (this.onMediaDone) this.onMediaDone(data.sceneId, data.eventId);
      if (status) status.textContent = "课程内容播放完毕";
    }
  },

  destroy: function () {
    if (this.messageHandler) {
      window.removeEventListener("message", this.messageHandler);
      this.messageHandler = null;
    }
    this.iframe = null;
    this.container = null;
  }
};

// Register on load — the legacy video-player.js exposes the bridge.
if (typeof window !== "undefined" && window.StudentAgentVideoPlayerBridge) {
  window.StudentAgentVideoPlayerBridge.register(platformPlayer);
} else {
  // Legacy module may not be loaded yet when this runs; retry after mount.
  Object.defineProperty(window, "StudentAgentVideoPlayerBridge", {
    configurable: true,
    set: function (bridge) {
      bridge.register(platformPlayer);
      Object.defineProperty(window, "StudentAgentVideoPlayerBridge", {
        value: bridge, configurable: true, writable: true
      });
    },
    get: function () { return undefined; }
  });
}

export default platformPlayer;
