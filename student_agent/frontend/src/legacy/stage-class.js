/* ═══════════════════════════════════════════════════════════
   「引导学习」这一幕的三个子界面
   idle（课前）→ chat（AI 对话）→ video（教学视频）

   切哪一幕由后端的 phase 决定（app.js 的 applySessionState）。
   这里只管这三块界面本身，以及把学生的动作转给后端：
     · 「开始上课」    → POST /begin
     · 输入框发言      → POST /message
     · 「视频已结束」  → POST /media/done

   ⚠️ 老师说的话**不在这里渲染**。后端的转录只有一份，由 app.js
   轮询 /messages 统一画；这里再 append 一次就会重复显示。
   ═══════════════════════════════════════════════════════════ */

import { $ } from "./ui.js";
import { mountVideoPlayer } from "./video-player.js";

export function createStage(ctx) {

  var composer = $("composer");
  var input = $("composer-input");
  var sendBtn = $("composer-send");
  var idle = $("stage-idle");
  var chat = $("stage-chat");
  var video = $("stage-video");

  var busy = false;
  var playerHandle = null;
  /* 已经为哪节课挂过播放器。enterVideo 会被反复调用，靠它做到幂等 */
  var videoMountedFor = null;

  /* ── 子阶段切换 ──────────────────────────────────────── */

  var PANES = { idle: idle, chat: chat, video: video };

  function showPane(name) {
    Object.keys(PANES).forEach(function (key) {
      PANES[key].hidden = key !== name;
    });
  }

  function setComposerEnabled(on) {
    input.disabled = !on;
    sendBtn.disabled = !on;
  }

  /* ── 课前：课时信息 ──────────────────────────────────── */

  function renderLesson(data) {
    $("lesson-eyebrow").textContent = data.course + " · " + data.chapter;
    $("lesson-title").textContent = data.title;
    $("lesson-summary").textContent = data.summary;
    $("meta-kp").textContent = data.knowledgePointCount;
    $("meta-seg").textContent = data.segmentCount;
    $("meta-min").textContent = data.estimatedMinutes;
  }

  /* ── 开始上课 ────────────────────────────────────────── */

  /* 起课铃。后端只认一次，重复按会 409 —— 正常按不到第二次，
     因为按钮的可用性由 available_actions 控制（app.js 的 renderActions）。 */
  function startLesson() {
    if (busy) return;
    busy = true;
    $("btn-start").disabled = true;

    ctx.teacherAction("begin").catch(function () {
      /* 失败了就让按钮回到后端说的状态，让学生能重试 */
      $("btn-start").disabled = ctx.getActions().indexOf("begin") === -1;
    }).then(function () { busy = false; });
  }

  /* ── 发言 ────────────────────────────────────────────── */

  /* 只把话发给后端。回复由轮询画出来 —— 这里 append 就会和后端
     转录里的同一条重上加重。 */
  function submitMessage(text) {
    busy = true;
    setComposerEnabled(false);

    ctx.sendMessage(text).catch(function () {
      /* 失败：把内容还回输入框，别让学生白打一遍 */
      if (!input.value) input.value = text;
    }).then(function () {
      busy = false;
      setComposerEnabled(true);
      input.focus();
    });
  }

  /* ── 教学视频 ────────────────────────────────────────── */

  function destroyPlayer() {
    if (playerHandle) playerHandle.destroy();
    playerHandle = null;
    videoMountedFor = null;
  }

  /* 进视频面板并挂上播放器。**幂等** —— 每次进 guided_learning 都会调，
     重复挂会把正在播的播放器打回原形。 */
  function enterVideo() {
    showPane("video");
    if (videoMountedFor === ctx.lessonId && playerHandle) return;

    var slot = $("video-player-slot");
    destroyPlayer();
    $("video-player-status").textContent = "正在准备播放器…";

    var lesson = ctx.getLesson();
    var first = lesson && lesson.segments && lesson.segments[0];
    var startSeconds = first && typeof first.startSeconds === "number" ? first.startSeconds : 0;

    try {
      playerHandle = mountVideoPlayer(slot, {
      lessonId: ctx.lessonId,
      lesson: lesson,
      classroomId: lesson && lesson.classroomId,
      /* 后端没有「取视频」的接口 —— 视频文件和播放完全归前端。
         业务方通过 window.StudentAgentVideoPlayer 注册自己的播放器；
         没注册时 mountVideoPlayer 会挂一个占位提示。 */
      video: null,
      startSeconds: startSeconds,
      onEnded: function () { notifyVideoEnd(); },
      onError: function (error) {
        var message = error && error.message ? error.message : String(error || "未知错误");
        $("video-player-status").textContent = "播放器错误：" + message;
        ctx.toast("播放器错误：" + message);
      }
      });
    } catch (error) {
      var mountMessage = error && error.message ? error.message : String(error || "未知错误");
      $("video-player-status").textContent = "播放器加载失败：" + mountMessage;
      slot.textContent = "播放器加载失败";
      ctx.toast("播放器加载失败：" + mountMessage);
      return;
    }
    videoMountedFor = ctx.lessonId;

    $("video-player-status").textContent = playerHandle.mounted
      ? "播放器已接入"
      : "等待接入外部视频播放器";
  }

  /* 通知后端视频播完了。后端 media_done 的语义是**整段视频全片播完、
     播完报一次**（这节课是 delivery:video，AI 全程不出讲解词）。 */
  function notifyVideoEnd() {
    $("video-player-status").textContent = "视频已播完，正在通知后端…";
    ctx.teacherAction("media_done").catch(function () {
      $("video-player-status").textContent = "通知失败，可以再点一次";
    });
  }

  /* ── 对外接口 ────────────────────────────────────────── */

  return {
    mount: function () {
      $("btn-start").addEventListener("click", startLesson);
      $("btn-skip-video").addEventListener("click", notifyVideoEnd);

      composer.addEventListener("submit", function (e) {
        e.preventDefault();
        var text = input.value.trim();
        if (!text || busy) return;
        input.value = "";
        input.style.height = "auto";
        submitMessage(text);
      });

      /* Enter 发送，Shift+Enter 换行 */
      input.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          composer.requestSubmit();
        }
      });

      /* 输入框自动增高 */
      input.addEventListener("input", function () {
        input.style.height = "auto";
        input.style.height = Math.min(input.scrollHeight, 132) + "px";
      });
    },

    enter: function (stage) {
      if (stage === "idle") {
        showPane("idle");
      } else if (stage === "chat") {
        showPane("chat");
      } else if (stage === "video") {
        enterVideo();
      }
    },

    leave: function () {
      destroyPlayer();
    },

    /* 换课：清掉输入、播放器和子面板，回到课前 */
    reset: function () {
      busy = false;
      setComposerEnabled(true);
      input.value = "";
      input.style.height = "auto";

      destroyPlayer();
      $("video-player-slot").replaceChildren();
      $("video-player-status").textContent = "等待接入外部视频播放器";

      showPane("idle");
    },

    enterVideo: enterVideo,
    renderLesson: renderLesson
  };
}
