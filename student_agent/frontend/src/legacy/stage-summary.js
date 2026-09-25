/* 总结复述：整整这一幕都是对话 —— AI 追问，学生接着答、接着补，直到编排器切走这一幕。
 *
 * 输入框**始终可用**：每答完一句，AI 的回复里就带着下一个问题或反馈。
 * 没有「我再改一版」—— 想补充直接接着说就行，不需要先"撤回"上一版。
 *
 * 什么时候离开这一幕由后端的 judge_advance 决定（证据够了 / 时间预算耗尽），
 * 前端不替它做决定（"前端不决定演到哪一幕"，见 README）。
 * 底下那个「进入下一阶段」按钮是**测试用**的：不想干等那几分钟时手动推一把。
 */
import { $, appendChatMessage, showTyping } from "./ui.js";
import { sendMessage, advanceStage } from "./api.js";

export function createStage(ctx) {
  var log = $("summary-log");
  var form = $("summary-composer");
  var input = $("summary-input");
  var count = $("summary-count");
  var submitBtn = $("summary-submit");
  var nextBtn = $("summary-next");
  var busy = false;

  function updateCount() {
    count.textContent = input.value.length + " / 600";
    count.classList.toggle("is-near", input.value.length > 510);
    // 这一幕是对话：老师在追问，学生的回答常常只有几个字，
    // 所以门槛跟探究阶段对齐（2 字），而不是"写一篇总结"的 10 字。
    submitBtn.disabled = busy || input.value.trim().length < 2;
  }

  function submit() {
    var text = input.value.trim();
    if (busy || text.length < 2) return;

    busy = true;
    input.disabled = true;
    var message = appendChatMessage(log, "me", text);
    input.value = "";
    updateCount();

    var stopTyping = showTyping(log);
    sendMessage(ctx.sessionId, text)
      .then(function (res) {
        stopTyping();
        // 回复里带的就是反馈或下一个问题，继续留在对话框里。
        // 轮询链路可能已投递同一条回复（replySeenByPoll 按 seq 判断），只渲染一次
        if (res.message.text && !ctx.replySeenByPoll(res)) {
          appendChatMessage(log, "ai", res.message.text);
        }
        ctx.applyServerTurn(res);
      })
      .catch(function (err) {
        stopTyping();
        message.remove();
        input.value = text;
        ctx.toast("发送失败：" + err.message);
      })
      .finally(function () {
        busy = false;
        input.disabled = false;
        updateCount();
        input.focus();
      });
  }

  /* 手动推进到下一幕。
     正常情况下切幕由后端的 judge_advance 决定（证据够了 / 预算耗尽），
     这个按钮是**测试用**的：不用等那几分钟就能往下走。
     它不影响对话式复述本身 —— 点不点都能接着复述。 */
  function goNext() {
    nextBtn.disabled = true;
    advanceStage(ctx.sessionId).then(function (res) {
      ctx.applyServerTurn(res);
      // 后端判定还不能走 → 放开按钮，学生可以接着复述
      if (ctx.getPhase() === "recap_discussion") nextBtn.disabled = false;
    }).catch(function (err) {
      nextBtn.disabled = false;
      ctx.toast("切幕失败：" + err.message);
    });
  }

  return {
    mount: function () {
      input.maxLength = 600;
      input.addEventListener("input", updateCount);
      input.addEventListener("keydown", function (event) {
        if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); form.requestSubmit(); }
      });
      form.addEventListener("submit", function (event) { event.preventDefault(); submit(); });
      nextBtn.addEventListener("click", goNext);
      updateCount();
    },
    enter: function (stage, turn) {
      if (turn && turn.message && turn.message.text) {
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
      input.value = "";
      input.disabled = false;
      busy = false;
      nextBtn.disabled = false;
      updateCount();
    }
  };
}
