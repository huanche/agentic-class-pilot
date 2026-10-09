/* 深入思考：题目与反馈均由后端依据当前 host_phase 生成。
   这一幕没有「进入下一阶段」按钮，由后端按证据/时间预算自动推进到收尾。 */
import { $, appendChatMessage, showTyping } from "./ui.js";
import { sendMessage } from "./api.js";

export function createStage(ctx) {
  var log = $("reflect-log");
  var form = $("reflect-composer");
  var input = $("reflect-input");
  var submitBtn = $("reflect-submit");
  var busy = false;

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
      updateSubmit();
    },
    enter: function (stage, turn) {
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
      updateSubmit();
    }
  };
}
