/* ═══════════════════════════════════════════════════════════
   课后辅导掌握条（工单 02 外壳）

   显示：复习剩余时间（服务端时间戳换算，刷新不清零）、
   知识点固定编号顺序（开场给学生的那套编号）、系统评定星级。
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
  var stars = tutoring.stars || {};
  var rubric = tutoring.rubric || {};
  var currentNo = tutoring.current_no;
  var rubricText = Object.keys(rubric).sort().map(function (k) {
    return k + "★ " + escapeHtml(rubric[k]);
  }).join("\n");
  var rows = order.map(function (no, index) {
    var kp = byNo[no];
    var star = stars[no];
    /* 高亮 = 正在讲的知识点（后端按复习顺序+游标下发 current_no）；
       旧载荷没有 current_no 时退回第一项 */
    var isCurrent = (typeof currentNo === "number")
      ? no === currentNo
      : index === 0;
    return '<li class="tm-item' + (isCurrent ? " tm-current" : "") + '">'
      + '<span class="tm-no">' + no + '</span>'
      + '<span class="tm-title">' + escapeHtml(kp.title) + '</span>'
      + (typeof star === "number" && star > 0
          ? '<span class="tm-stars">掌握 ' + star + "★</span>" : '<span class="tm-stars">未检测</span>')
      + ((tutoring.needs_review || []).includes(no) ? '<span class="tm-review">需要再确认</span>' : "")
      + (rubricText
          ? '<button type="button" class="tm-rubric" aria-label="评分标准"'
            + ' aria-expanded="false" title="评分标准">ⓘ</button>'
            + '<span class="tm-rubric-text">' + rubricText + "</span>"
          : "")
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

  /* 触屏点击切换（悬停/键盘聚焦由 CSS 处理）；重渲染只换 innerHTML，
     容器上的监听器绑一次就够。不用 hidden 属性——globals.css 把
     [hidden] 定成了 display:none!important，会压掉悬停/聚焦的显示规则。 */
  if (!el.__tmBound) {
    el.addEventListener("click", function (event) {
      var btn = event.target && event.target.closest ? event.target.closest(".tm-rubric") : null;
      if (!btn || !el.contains(btn)) return;
      var item = btn.parentElement;
      var text = item && item.querySelector(".tm-rubric-text");
      if (!text) return;
      var opening = !text.classList.contains("tm-open");
      text.classList.toggle("tm-open", opening);
      btn.setAttribute("aria-expanded", opening ? "true" : "false");
      if (!opening) btn.blur();   // 关闭时移开焦点，否则 :focus 规则会把它继续撑着
    });
    el.__tmBound = true;
  }
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
