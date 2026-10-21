/* ═══════════════════════════════════════════════════════════
   课后辅导反馈卡（工单 05）

   渲染 GET /api/session/<sid>/tutoring-report 的最新版反馈：
   各知识点终值星级与证据条数、复习用时、答题统计、
   未完成检测、后续建议。
   只渲染学生视角——教师摘要已入库，但不在学生端展示。
   ═══════════════════════════════════════════════════════════ */

import { el } from "./ui.js";

export function renderTutoringReportCard(container, report) {
  if (!container) return;
  container.replaceChildren();
  if (!report || !report.payload) return;
  var p = report.payload;
  var stats = p.stats || {};

  var card = el("section", "tfeedback");
  card.appendChild(el("h3", "tfeedback__title",
    "课后辅导反馈（第 " + report.version + " 版）"));

  var meta = el("p", "tfeedback__meta");
  meta.textContent = "复习约 " + (p.actual_minutes == null ? "–" : p.actual_minutes)
    + " 分钟（计划 " + (p.planned_minutes == null ? "–" : p.planned_minutes) + "）"
    + " · 出题 " + (p.asked_questions || 0) + " 道"
    + " · 答对 " + (stats.correct || 0)
    + " · 答错 " + (stats.wrong || 0);
  card.appendChild(meta);

  var list = el("ul", "tfeedback__kps");
  (p.knowledge_points || []).forEach(function (k) {
    var row = el("li", "tfeedback__kp");
    row.appendChild(el("span", "tfeedback__no", (k.no || "") + "."));
    row.appendChild(el("span", "tfeedback__name", k.title || ""));
    row.appendChild(el("span", "tfeedback__stars",
      (k.system_stars || 0) > 0 ? "掌握 " + k.system_stars + "★" : "未检测"));
    if (k.needs_review) row.appendChild(el("span", "tfeedback__review", "需要再确认"));
    var evidence = k.evidence || [];
    row.appendChild(el("span", "tfeedback__evidence",
      evidence.length ? "依据 " + evidence.length + " 条" : ""));
    list.appendChild(row);
  });
  card.appendChild(list);

  if (p.unfinished_question) {
    card.appendChild(el("p", "tfeedback__unfinished",
      "未完成检测：" + p.unfinished_question));
  }
  if (p.advice) {
    card.appendChild(el("p", "tfeedback__advice", p.advice));
  }
  container.appendChild(card);
}
