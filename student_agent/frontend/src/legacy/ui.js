/* ═══════════════════════════════════════════════════════════
   共用工具
   纯函数与 DOM 小助手，不依赖任何其它模块
   ═══════════════════════════════════════════════════════════ */

export function $(id) {
  return document.getElementById(id);
}

export var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function delay(ms) {
  return new Promise(function (resolve) { setTimeout(resolve, ms); });
}

/* ── 元素构造 ────────────────────────────────────────────── */

export function el(tag, className, text) {
  var node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

/* 图标一律来自代码里的静态字符串，不含用户输入，可安全用 innerHTML */
export function icon(paths, size) {
  var span = document.createElement("span");
  span.className = "icon";
  span.style.width = span.style.height = (size || 16) + "px";
  span.innerHTML =
    '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round" stroke-linejoin="round">' + paths + "</svg>";
  return span;
}

/* ── 文本安全 ────────────────────────────────────────────── */

var ESCAPE_MAP = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

export function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, function (ch) { return ESCAPE_MAP[ch]; });
}

/* 先转义再解析 **粗体**，顺序不能反 */
export function renderInline(text) {
  return escapeHtml(text).replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

/* ── 视图 ────────────────────────────────────────────────── */

export function visibleRoot() {
  var nodes = document.querySelectorAll(".hub, .view");
  for (var i = 0; i < nodes.length; i++) {
    if (!nodes[i].hidden) return nodes[i];
  }
  return null;
}

export function scrollToEnd(node) {
  node.scrollTop = node.scrollHeight;
}

export function appendChatMessage(log, role, text) {
  var row = el("div", "msg msg--" + role);
  if (role === "ai") row.appendChild(el("span", "msg__avatar", "师"));
  var bubble = el("div", "msg__bubble");
  bubble.innerHTML = renderInline(text);
  row.appendChild(bubble);
  log.appendChild(row);
  scrollToEnd(log);
  return row;
}

/* ── 「AI 正在输入」的三个点 ──────────────────────────────── */

/** 三点气泡**本体**（不含外层行）。className 套各阶段的样式，如 "msg__bubble"。 */
export function typingBubble(className) {
  var bubble = el("div", (className ? className + " " : "") + "typing");
  bubble.innerHTML = "<span></span><span></span><span></span>";
  return bubble;
}

/** 会话区通用版：一行 .msg--ai + 三点气泡。返回移除它的函数。
 *
 *  调用方**拿到回复时要立刻调用**返回的函数，否则点会压在 AI 消息上面。
 *
 *  复述/探究三幕原来只在等待期间把输入框禁用，没有任何"AI 在想"的反馈 ——
 *  之前响应是瞬间的看不出来，接了真实大模型之后每轮要等好几秒就很明显。
 *  （讲解阶段 stage-class.js 更早就有自己的一份，这里没动它，避免碰working的路径。）
 */
export function showTyping(log, avatar) {
  var row = el("div", "msg msg--ai");
  row.dataset.typing = "1";
  row.appendChild(el("span", "msg__avatar", avatar || "师"));
  row.appendChild(typingBubble("msg__bubble"));
  log.appendChild(row);
  scrollToEnd(log);
  return function hideTyping() { row.remove(); };
}

/* ── 轻提示 ──────────────────────────────────────────────── */

export function showToast(text) {
  var old = document.querySelector(".toast");
  if (old) old.remove();

  var node = el("div", "toast", text);
  document.body.appendChild(node);

  setTimeout(function () {
    node.classList.add("is-leaving");
    setTimeout(function () { node.remove(); }, 300);
  }, 2600);
}
