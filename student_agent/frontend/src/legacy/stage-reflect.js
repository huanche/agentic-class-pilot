/* 深入思考：题目与反馈均由后端依据当前 host_phase 生成。
   正常情况下由后端按证据/时间预算自动推进到收尾；
   底下那个「结束本节课」按钮是快捷出口：至少对话 2 分钟才放行，直接下课。 */
import { $, appendChatMessage, showTyping } from "./ui.js";
import { sendMessage, endLesson } from "./api.js";

export function createStage(ctx) {
  var log = $("reflect-log");
  var form = $("reflect-composer");
  var input = $("reflect-input");
  var submitBtn = $("reflect-submit");
  var endBtn = $("reflect-end");
  var busy = false;

  /* 「结束本节课」按钮的对话时长门槛：这一幕至少对话 2 分钟才放行，
     避免学生还没思考几句就急着下课。 */
  var stageStartedAt = 0;
  var MIN_DIALOGUE_MS = 2 * 60 * 1000;

  function updateSubmit() {
    submitBtn.disabled = busy || input.value.trim().length < 2;
  }

  function submit() {
    var answer = input.value.trim();
    if (busy || answer.length < 2) return;
    busy = true;
    input.disabled = true;
    var row = appendChatMessage(log, "me", answer);
    input.value = "";
    updateSubmit();
    var stopTyping = showTyping(log);
    sendMessage(ctx.sessionId, answer).then(function (res) {
      stopTyping();
      /* 轮询链路可能已投递同一条回复（replySeenByPoll 按 seq 判断），只渲染一次 */
      if (res.message.text && !ctx.replySeenByPoll(res)) {
        appendChatMessage(log, "ai", res.message.text);
      }
      ctx.applyServerTurn(res);
    }).catch(function (err) {
      stopTyping();
      row.remove();
      input.value = answer;
      ctx.toast("提交失败：" + err.message);
    }).finally(function () {
      busy = false;
      input.disabled = false;
      updateSubmit();
      input.focus();
    });
  }

  /* 主动结束本节课（跳过剩余阶段直接下课）。
     正常情况下下课由后端的 judge_advance 决定（预算耗尽），
     这个按钮是快捷出口，但这一幕至少对话 2 分钟才放行。 */
  function end() {
    if (Date.now() - stageStartedAt < MIN_DIALOGUE_MS) {
      ctx.toast("请继续对话");
      return;
    }
    endBtn.disabled = true;
    endLesson(ctx.sessionId).then(function (res) {
      ctx.applyServerTurn(res);
      // 后端仍留在深入思考（没真正下课）→ 放开按钮，学生可以接着说
      if (ctx.getPhase() === "deep_inquiry") endBtn.disabled = false;
    }).catch(function (err) {
      endBtn.disabled = false;
      ctx.toast("结束失败：" + err.message);
    });
  }

  return {
    mount: function () {
      input.maxLength = 600;
      input.addEventListener("input", updateSubmit);
      input.addEventListener("keydown", function (event) {
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          form.requestSubmit();
        }
      });
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        submit();
      });
      endBtn.addEventListener("click", end);
      updateSubmit();
    },
    enter: function (stage, turn) {
      stageStartedAt = Date.now();
      if (!log.children.length && turn && turn.message && turn.message.text) {
        appendChatMessage(log, "ai", turn.message.text);
      }
      input.focus();
    },
    leave: function () {},
    receiveMessage: function (text) {
      appendChatMessage(log, "ai", text);
    },
    reset: function () {
      log.innerHTML = "";
      busy = false;
      input.value = "";
      input.disabled = false;
      form.hidden = false;
      endBtn.disabled = false;
      stageStartedAt = 0;
      updateSubmit();
    }
  };
}
