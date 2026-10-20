/* ═══════════════════════════════════════════════════════════
   课程结束态
   四个阶段走完后收束：本节课覆盖的知识点 + 去课后的入口
   ═══════════════════════════════════════════════════════════ */

import { $, el } from "./ui.js";

export function createStage(ctx) {

  var list = $("done-kps");

  function renderKnowledgePoints() {
    /* 知识点目录与辅导同源（/state 的固定编号清单）——课时文件里的
       静态列表和真实目录会漂移（演示课 8 条 vs 辅导 6 条），不再用它；
       目录还没到（旧后端）时才回退到课时清单。 */
    var catalog = ctx.getKnowledgeCatalog && ctx.getKnowledgeCatalog();
    list.replaceChildren();
    if (catalog && catalog.length) {
      catalog.forEach(function (kp) {
        var item = el("li", "done__kp");
        item.appendChild(el("span", "done__kp-num", String(kp.no)));
        item.appendChild(el("span", "done__kp-name", kp.title));
        list.appendChild(item);
      });
      return;
    }
    var lesson = ctx.getLesson();
    if (!lesson || !lesson.knowledgePoints) return;
    lesson.knowledgePoints.forEach(function (name, i) {
      var item = el("li", "done__kp");
      item.appendChild(el("span", "done__kp-num", String(i + 1)));
      item.appendChild(el("span", "done__kp-name", name));
      list.appendChild(item);
    });
  }

  return {
    mount: function () {
      $("done-to-review").addEventListener("click", function () {
        /* 去「课后」（内容待定，现在是占位） */
        location.hash = ctx.getReviewHash();
      });
    },

    enter: function () {
      ctx.setStatus("已结束");
      renderKnowledgePoints();
    },

    leave: function () {}
  };
}
