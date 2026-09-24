/* 外部视频播放器适配层。
   项目本身不创建播放器；业务方注册 adapter 后接管挂载区域。 */

var registeredAdapter = null;

function isAdapter(value) {
  return value && typeof value.mount === "function";
}

export function registerVideoPlayer(adapter) {
  if (!isAdapter(adapter)) {
    throw new TypeError("视频播放器 adapter 必须提供 mount(container, context) 方法");
  }
  registeredAdapter = adapter;
}

export function mountVideoPlayer(container, context) {
  container.replaceChildren();

  var adapter = registeredAdapter;
  if (!adapter && typeof window !== "undefined" && isAdapter(window.StudentAgentVideoPlayer)) {
    adapter = window.StudentAgentVideoPlayer;
  }

  if (!adapter) {
    container.dataset.playerState = "waiting";
    container.textContent = "视频播放器待接入";
    return { mounted: false, destroy: function () { container.replaceChildren(); } };
  }

  delete container.dataset.playerState;
  var cleanup = adapter.mount(container, context);
  return {
    mounted: true,
    destroy: function () {
      if (typeof cleanup === "function") cleanup();
      else if (cleanup && typeof cleanup.destroy === "function") cleanup.destroy();
      container.replaceChildren();
    }
  };
}

if (typeof window !== "undefined") {
  window.StudentAgentVideoPlayerBridge = {
    register: registerVideoPlayer
  };
}
