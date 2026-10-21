/* ═══════════════════════════════════════════════════════════
   课后辅导掌握条（工单 02 外壳）

   显示：复习剩余时间（服务端时间戳换算，刷新不清零）、
   知识点固定编号顺序（开场给学生的那套编号）与名称。
   顶部不展示星级、掌握状态或评分说明，详细结果在报告中查看。
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

/* ── 倒计时：本地每秒走秒，以服务端 remaining 为锚 ──
   会话轮询 2 秒一次，直接重渲染会让倒计时每 2 秒跳一下。
   渲染时把锚点（服务端剩余秒数 + 本地收到时刻）记在时钟元素上，
   一个全局 1 秒 ticker 只改时钟文本；轮询重渲染刷新锚点（校准漂移）。 */
var clockTimer = null;

function ensureClockTicker() {
  if (clockTimer) return;
  clockTimer = setInterval(function () {
    var nodes = document.querySelectorAll(".tm-clock[data-remaining]");
    for (var i = 0; i < nodes.length; i++) {
      var node = nodes[i];
      var remaining = parseFloat(node.getAttribute("data-remaining"));
      var at = parseFloat(node.getAttribute("data-at")) || 0;
      if (!isFinite(remaining) || !at) continue;
      var left = remaining - (Date.now() - at) / 1000;
      node.textContent = formatRemaining(Math.max(0, Math.round(left)));
    }
  }, 1000);
}

export function renderTutoringMastery(el, tutoring) {
  if (!el || !tutoring) return;
  var kps = tutoring.knowledge_points || [];
  var byNo = {};
  kps.forEach(function (kp) { byNo[kp.no] = kp; });
  var order = (tutoring.order || []).filter(function (no) { return byNo[no]; });
  var currentNo = tutoring.current_no;
  var rows = order.map(function (no, index) {
    var kp = byNo[no];
    /* 高亮 = 正在讲的知识点（后端按复习顺序+游标下发 current_no）；
       旧载荷没有 current_no 时退回第一项 */
    var isCurrent = (typeof currentNo === "number")
      ? no === currentNo
      : index === 0;
    return '<li class="tm-item' + (isCurrent ? " tm-current" : "") + '">'
      + '<span class="tm-no">' + no + '</span>'
      + '<span class="tm-title">' + escapeHtml(kp.title) + '</span>'
      + "</li>";
  });
  var remaining = formatRemaining(tutoring.remaining_seconds);
  var clockAttrs = "";
  if (typeof tutoring.remaining_seconds === "number") {
    clockAttrs = ' data-remaining="' + tutoring.remaining_seconds
      + '" data-at="' + Date.now() + '"';
  }
  el.innerHTML =
    '<div class="tm-head">复习剩余 <span class="tm-clock"' + clockAttrs + ">"
    + (remaining || "--:--") + "</span></div>"
    + '<ol class="tm-list">' + rows.join("") + "</ol>";
  ensureClockTicker();

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
