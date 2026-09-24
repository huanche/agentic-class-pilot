/* ═══════════════════════════════════════════════════════════
   外观主题：浅色 / 深色 / 跟随系统

   属性 html[data-theme] 只有 light / dark 两个值 —— 「跟随系统」
   由本模块监听 media query 后代为写入，这样 CSS 只需一套深色规则。

   首屏防闪由 src/app/layout.js <head> 里的一小段内联脚本负责，
   它会在样式表生效前就把 data-theme 设好。
   ═══════════════════════════════════════════════════════════ */

import { $, el } from "./ui.js";

export var STORAGE_KEY = "ai-learn.theme";

export var MODES = [
  { key: "light", label: "浅色" },
  { key: "dark",  label: "深色" },
  { key: "auto",  label: "跟随系统" }
];

/* 图标：16×16 线性，粗细与项目里其它图标一致 */
var ICONS = {
  light:
    '<circle cx="8" cy="8" r="3.1"/>' +
    '<path d="M8 1.2v1.9M8 12.9v1.9M14.8 8h-1.9M3.1 8H1.2' +
    'M12.8 3.2l-1.3 1.3M4.5 11.5l-1.3 1.3M12.8 12.8l-1.3-1.3M4.5 4.5L3.2 3.2"/>',
  dark:
    '<path d="M13.4 9.6A5.7 5.7 0 0 1 6.4 2.2a5.8 5.8 0 1 0 7 7.4z"/>',
  auto:
    '<circle cx="8" cy="8" r="5.9"/>' +
    '<path d="M8 2.1a5.9 5.9 0 0 1 0 11.8z" fill="currentColor" stroke="none"/>'
};

var media = window.matchMedia("(prefers-color-scheme: dark)");

function systemTheme() {
  return media.matches ? "dark" : "light";
}

/* 读存储的偏好；没存过就是 auto */
export function savedMode() {
  try {
    var value = localStorage.getItem(STORAGE_KEY);
    if (value === "light" || value === "dark" || value === "auto") return value;
  } catch (e) { /* 隐私模式下 localStorage 可能不可用 */ }
  return "auto";
}

export function resolvedTheme(mode) {
  return mode === "auto" ? systemTheme() : mode;
}

export function applyMode(mode) {
  document.documentElement.dataset.theme = resolvedTheme(mode);
}

function saveMode(mode) {
  try { localStorage.setItem(STORAGE_KEY, mode); } catch (e) { /* 忽略 */ }
}


/* ═══════════════════════════════════════════════════════════
   右上角的切换控件
   ═══════════════════════════════════════════════════════════ */

export function createThemeSwitch() {
  var root = $("theme-switch");
  var btn = $("theme-btn");
  var menu = $("theme-menu");

  var mode = savedMode();
  var open = false;

  function iconSvg(key) {
    return '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" ' +
      'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' +
      ICONS[key] + "</svg>";
  }

  /* 按钮图标跟随「当前实际生效」的外观，而不是所选模式 ——
     跟随系统时，显示的是系统当前那个（日光或月亮），一眼能看懂 */
  function paintButton() {
    btn.innerHTML = iconSvg(resolvedTheme(mode));
    btn.setAttribute("aria-label", "外观：" + currentLabel());
    btn.title = "外观：" + currentLabel();
  }

  function currentLabel() {
    var found = MODES.filter(function (m) { return m.key === mode; })[0];
    return found ? found.label : "跟随系统";
  }

  function paintMenu() {
    menu.innerHTML = "";
    MODES.forEach(function (item) {
      var row = el("button", "theme-menu__item");
      row.type = "button";
      row.setAttribute("role", "menuitemradio");
      row.setAttribute("aria-checked", String(item.key === mode));
      row.dataset.setTheme = item.key;

      var glyph = el("span", "theme-menu__icon");
      glyph.innerHTML = iconSvg(item.key);
      row.appendChild(glyph);

      row.appendChild(el("span", "theme-menu__label", item.label));

      var check = el("span", "theme-menu__check", "✓");
      row.appendChild(check);

      row.addEventListener("click", function () {
        setMode(item.key);
        closeMenu();
      });

      menu.appendChild(row);
    });
  }

  function setMode(next) {
    mode = next;
    applyMode(mode);
    saveMode(mode);
    paintButton();
    paintMenu();
  }

  function openMenu() {
    open = true;
    menu.hidden = false;
    btn.setAttribute("aria-expanded", "true");
    /* 重放入场动画，菜单每次都「弹」出来 */
    menu.style.animation = "none";
    void menu.offsetWidth;
    menu.style.animation = "";
  }

  function closeMenu() {
    open = false;
    menu.hidden = true;
    btn.setAttribute("aria-expanded", "false");
  }

  /* ── 事件 ───────────────────────────────────────────── */

  btn.addEventListener("click", function (e) {
    e.stopPropagation();
    if (open) closeMenu();
    else openMenu();
  });

  /* 点别处关掉 */
  document.addEventListener("click", function (e) {
    if (open && !root.contains(e.target)) closeMenu();
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && open) {
      closeMenu();
      btn.focus();
    }
  });

  /* 跟随系统时，系统外观一变就跟着变 */
  var onSystemChange = function () {
    if (mode === "auto") {
      applyMode(mode);
      paintButton();
    }
  };
  if (media.addEventListener) media.addEventListener("change", onSystemChange);
  else if (media.addListener) media.addListener(onSystemChange);

  /* ── 初始化 ─────────────────────────────────────────── */

  paintButton();
  paintMenu();

  return {
    setMode: setMode,
    getMode: function () { return mode; },
    /* 只在入口页显示 */
    setVisible: function (visible) {
      root.hidden = !visible;
      if (!visible) closeMenu();
    }
  };
}
