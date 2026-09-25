/* 课堂讨论仍使用同一个 AI 会话；当前不是多人聊天室。 */
import { $, el, scrollToEnd, typingBubble } from "./ui.js";
import { sendMessage, advanceStage } from "./api.js";

export function createStage(ctx) {
  var topicBox = $("discuss-topic");
  var log = $("discuss-log");
  var composer = $("discuss-composer");
  var input = $("discuss-input");
  var endBtn = $("discuss-end");
  var busy = false;

  function renderMessage(speaker, text) {
    if (!text) return;
    var mine = speaker === "me";
    var row = el("div", "dm dm--" + (mine ? "me" : "host"));
    if (!mine) row.appendChild(el("div", "dm__avatar", "AI"));
    var body = el("div", "dm__body");
    var head = el("div", "dm__head");
    head.appendChild(el("span", "dm__name", mine ? "我" : "AI 老师"));
    head.appendChild(el("span", "dm__time", new Date().toTimeString().slice(0, 5)));
    body.appendChild(head);
    body.appendChild(el("div", "dm__bubble", text));
    row.appendChild(body);
    log.appendChild(row);
    scrollToEnd(log);
  }

  /* 讨论区是另一套标记（.dm--host），加载点也得照它的结构拼 */
  function showTyping() {
    var row = el("div", "dm dm--host");
    row.dataset.typing = "1";
    row.appendChild(el("div", "dm__avatar", "AI"));
    var body = el("div", "dm__body");
    body.appendChild(typingBubble("dm__bubble"));
    row.appendChild(body);
    log.appendChild(row);
    scrollToEnd(log);
    return function hideTyping() { row.remove(); };
  }

  function send(text) {
    if (busy) return;
    busy = true;
    input.disabled = true;
    $("discuss-send").disabled = true;
    renderMessage("me", text);
    var stopTyping = showTyping();
    sendMessage(ctx.sessionId, text).then(function (res) {
      stopTyping();
      renderMessage("host", res.message.text);
      ctx.applyServerTurn(res);
      endBtn.hidden = false;
    }).catch(function (err) {
      stopTyping();
      ctx.toast("发送失败：" + err.message);
    }).finally(function () {
      busy = false;
      input.disabled = false;
      $("discuss-send").disabled = false;
      input.focus();
    });
  }

  return {
    mount: function () {
      topicBox.textContent = "围绕当前课程问题，与 AI 老师继续讨论。";
      composer.addEventListener("submit", function (event) {
        event.preventDefault();
        var text = input.value.trim();
        if (!text) return;
        input.value = "";
        send(text);
      });
      input.addEventListener("keydown", function (event) {
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          composer.requestSubmit();
        }
      });
      endBtn.addEventListener("click", function () {
        endBtn.disabled = true;
        advanceStage(ctx.sessionId).then(function (res) {
          renderMessage("host", res.message.text);
          ctx.applyServerTurn(res);
        }).catch(function (err) {
          endBtn.disabled = false;
          ctx.toast("结束失败：" + err.message);
        });
      });
    },
    enter: function (stage, turn) {
      if (!log.children.length && turn && turn.message) renderMessage("host", turn.message.text);
      input.focus();
    },
    leave: function () {},
    receiveMessage: function (text) {
      renderMessage("host", text);
    },
    reset: function () {
      log.innerHTML = "";
      input.value = "";
      input.disabled = false;
      busy = false;
      endBtn.hidden = true;
      endBtn.disabled = false;
    }
  };
}
