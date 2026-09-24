/* ═══════════════════════════════════════════════════════════
   阶段 4：课堂讨论（class_discussion）

   ⚠️ 这节课在 lesson-data/lesson-plan.json 里 class_discussion 是
   `enabled: false`，所以**这一幕根本不会出现**，这个面板正常情况下看不到。

   那为什么还留着？因为它接的是后端的通用一问一答，而不是 mock 里那套
   「老师 / 同学 / 我」三方讨论 —— 后端**没有**多人结构（student_id 全链路
   硬编码，数据库里也没有班级/讨论组），mock 里的同学发言和老师追问都是
   前端本地伪造的，接真后端后必须去掉。

   留着它是为了让「万一哪天后端开了讨论阶段」不至于崩：到时候它就是一个
   普通的一问一答面板。
   ═══════════════════════════════════════════════════════════ */

import { $ } from "./ui.js";

export function createStage(ctx) {

  var form = $("discuss-composer");
  var input = $("discuss-input");
  var sendBtn = $("discuss-send");
  var nextBtn = $("discuss-end");

  var busy = false;

  function updateSubmit() {
    sendBtn.disabled = busy || !input.value.trim();
  }

  function submit() {
    var text = input.value.trim();
    if (busy || !text) return;

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
      $("discuss-topic").textContent =
        "这一环节由老师主持。有想法就发上来，AI 老师会接着往下带。";
      /* 按钮文案由 app.js 的 renderActions() 统一给（最后一幕会说「结束课程」），
         这里只负责让它可见 */
      nextBtn.hidden = false;

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
