/* ═══════════════════════════════════════════════════════════
   课后辅导掌握条（工单 02 外壳）

   显示：复习剩余时间（服务端时间戳换算，刷新不清零）、
   知识点固定编号顺序（开场给学生的那套编号）、学生自评。
   星级区由工单 03 填充（数据到了就渲染，本模块不重算）。
   ═══════════════════════════════════════════════════════════ */

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, function (ch) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
  });
}

function formatRemaining(seconds) {
  if (typeof seconds !== "number") return "";
  var m = Math.floor(seconds / 60);
  var s = Math.floor(seconds % 60);
  return m + ":" + (s < 10 ? "0" : "") + s;
}

export function renderTutoringMastery(el, tutoring) {
  if (!el || !tutoring) return;
  var kps = tutoring.knowledge_points || [];
  var byNo = {};
  kps.forEach(function (kp) { byNo[kp.no] = kp; });
  var order = (tutoring.order || []).filter(function (no) { return byNo[no]; });
  var ratings = tutoring.self_ratings || {};
  var stars = tutoring.stars || {};
  var rows = order.map(function (no, index) {
    var kp = byNo[no];
    var rating = ratings[no];
    var star = stars[no];
    return '<li class="tm-item' + (index === 0 ? " tm-current" : "") + '">'
      + '<span class="tm-no">' + no + '</span>'
      + '<span class="tm-title">' + escapeHtml(kp.title) + '</span>'
      + (typeof star === "number" && star > 0
          ? '<span class="tm-stars">系统 ' + star + "★</span>" : "")
      + (rating ? '<span class="tm-self">自评 ' + rating + "★</span>" : "")
      + "</li>";
  });
  var remaining = formatRemaining(tutoring.remaining_seconds);
  el.innerHTML =
    '<div class="tm-head">复习剩余 <span class="tm-clock">'
    + (remaining || "--:--") + "</span></div>"
    + '<ol class="tm-list">' + rows.join("") + "</ol>";
}

export function mountTutoringMastery(host) {
  if (!host) return null;
  var el = document.createElement("div");
  el.id = "tutoring-mastery";
  el.className = "tutoring-mastery";
  /* 前置插入：掌握条在聊天记录上方，不把 composer 挤出屏幕 */
  host.insertBefore(el, host.firstChild);
  return el;
}
