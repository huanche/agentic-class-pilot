/* ═══════════════════════════════════════════════════════════
   阶段 2：总结复述（recap_discussion）

   后端在这一幕是「一问一答」：它抛出当前问题（/state 的 current_question），
   学生用自然语言答，它给反馈并判星。

   ⚠️ 前端 mock 里那套「讲对的 / 遗漏的 / 补充 / 和以前内容的关联」结构化
   反馈**后端没有这个接口**，所以「我再改一版」那个按钮也去掉了 ——
   留着一个转不动的按钮比没有更糟。

   老师说的话和 AI 的反馈由 app.js 轮询 /messages 统一画，
   这个面板只管收字、发出去。
   ═══════════════════════════════════════════════════════════ */

import { $ } from "./ui.js";

export function createStage(ctx) {

  var form = $("summary-composer");
  var input = $("summary-input");
  var count = $("summary-count");
  var submitBtn = $("summary-submit");
  var nextBtn = $("summary-next");

  var busy = false;

  function updateCount() {
    count.textContent = input.value.length + " / 600";
    count.classList.toggle("is-near", input.value.length > 510);
    submitBtn.disabled = busy || input.value.trim().length < 10;
  }

  function submit() {
    var text = input.value.trim();
    if (busy || text.length < 10) return;

    busy = true;
    input.disabled = true;
    input.value = "";
    updateCount();

    ctx.sendMessage(text).catch(function () {
      /* 失败：把内容还回输入框，别让学生白打一遍 */
      if (!input.value) input.value = text;
    }).then(function () {
      busy = false;
      input.disabled = false;
      updateCount();
    });
  }

  /* 「进入下一环节」是老师的 next_stage 动作 —— 无条件切幕。
     能不能按由后端的 available_actions 说了算（app.js 的 renderActions）。 */
  function nextStage() {
    nextBtn.disabled = true;
    ctx.teacherAction("next_stage").catch(function () {
      /* 失败就按后端说的重算，别卡死在禁用态 */
      nextBtn.disabled = ctx.getActions().indexOf("next_stage") === -1;
    });
  }

  return {
    mount: function () {
      input.maxLength = 600;
      input.addEventListener("input", updateCount);
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
      nextBtn.addEventListener("click", nextStage);
      updateCount();
    },

    enter: function () {
      updateCount();
      input.focus();
    },

    leave: function () {},

    reset: function () {
      input.value = "";
      input.disabled = false;
      busy = false;
      nextBtn.disabled = false;
      updateCount();
    }
  };
}
