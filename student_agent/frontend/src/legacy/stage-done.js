/* ═══════════════════════════════════════════════════════════
   课程结束态
   四个阶段走完后收束：本节课覆盖的知识点 + 去课后的入口
   ═══════════════════════════════════════════════════════════ */

import { $, el } from "./ui.js";
import { fetchSessionState } from "./api.js";

export function createStage(ctx) {

  var list = $("done-kps");
  var summaryCard = el("section", "done__summary");
  summaryCard.hidden = true;
  summaryCard.appendChild(el("p", "done__kps-label", "下课小结"));
  var summaryText = el("p", "done__summary-text");
  summaryText.id = "done-summary";
  summaryCard.appendChild(summaryText);
  list.parentNode.parentNode.insertBefore(summaryCard, list.parentNode);
  var requestSeq = 0;
  var hasSavedSummary = false;

  function showSummary(text, saved) {
    if (!text) return;
    summaryText.textContent = text;
    summaryCard.hidden = false;
    if (saved) hasSavedSummary = true;
  }

  function updateSummary(turn) {
    if (!turn) return;
    showSummary(turn.endingSummary || turn.ending_summary, true);
  }

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

    enter: function (_name, turn) {
      ctx.setStatus("已结束");
      renderKnowledgePoints();
      var seq = ++requestSeq;
      var sid = ctx.sessionId;
      hasSavedSummary = false;
      summaryText.textContent = "";
      summaryCard.hidden = true;
      updateSummary(turn);
      if (!hasSavedSummary && turn && turn.message) showSummary(turn.message.text, false);
      if (!hasSavedSummary) {
        fetchSessionState(sid).then(function (state) {
          if (seq !== requestSeq || ctx.sessionId !== sid) return;
          if ((state.hostPhase || state.phase) === "ending") updateSummary(state);
        }).catch(function () { /* 已显示的回复继续保留，后续轮询仍可补齐小结。 */ });
      }
    },

    updateSummary: updateSummary,

    receiveMessage: function (text) {
      if (!hasSavedSummary) showSummary(text, false);
    },

    leave: function () { requestSeq++; }
  };
}
