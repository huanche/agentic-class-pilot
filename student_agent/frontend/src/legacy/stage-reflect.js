/* ═══════════════════════════════════════════════════════════
   阶段 3：深入思考（deep_inquiry）

   后端在这一幕同样是「一问一答」—— 它按 KNOWLEDGE-BASE.md 里
   四个探究字段（为什么/如何、实际问题、跨学科关联…）自己出题。

   ⚠️ 前端 mock 里那套「底层逻辑 / 实际问题 / 跨学科关联 三个视角逐个点评」
   是前端自己编的题（REFLECTION_LENSES），后端没有对应接口。现在题由后端抛，
   这个面板不再自己造题，只管收字、发出去。
   ═══════════════════════════════════════════════════════════ */

import { $ } from "./ui.js";

export function createStage(ctx) {

  var form = $("reflect-composer");
  var input = $("reflect-input");
  var submitBtn = $("reflect-submit");
  var nextBtn = $("reflect-next");

  var busy = false;
  var MIN_LEN = 6;

  function updateSubmit() {
    submitBtn.disabled = busy || input.value.trim().length < MIN_LEN;
  }

  function submit() {
    var text = input.value.trim();
    if (busy || text.length < MIN_LEN) return;

    busy = true;
    input.disabled = true;
    input.value = "";
    updateSubmit();

    ctx.sendMessage(text).catch(function () {
      if (!input.value) input.value = text;
    }).then(function () {
      busy = false;
      input.disabled = false;
      updateSubmit();
    });
  }

  function nextStage() {
    nextBtn.disabled = true;
    ctx.teacherAction("next_stage").catch(function () {
      nextBtn.disabled = ctx.getActions().indexOf("next_stage") === -1;
    });
  }

  return {
    mount: function () {
      input.maxLength = 400;
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
      nextBtn.addEventListener("click", nextStage);
      updateSubmit();
    },

    enter: function () {
      updateSubmit();
      input.focus();
    },

    leave: function () {},

    reset: function () {
      input.value = "";
      input.disabled = false;
      busy = false;
      nextBtn.disabled = false;
      updateSubmit();
    }
  };
}
