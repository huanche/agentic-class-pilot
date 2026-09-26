/* ═══════════════════════════════════════════════════════════
   课后 · 学习报告

   把学生在这节课上的学习情况汇总成一页：知识点掌握、各阶段表现、
   课后建议。数据来自后端「主动引导智能体」的学情导出
     GET /api/session/<sessionId>/export?fmt=json
   （接口层见 api.js 第 ⑧ 节）

   只渲染**学生部分**。后端那份导出里还带着 student_id、会话 id、
   advance_reason、stage_snapshots[].evidence 原话、以及 targets_* 里
   的 KP-xxx 内部编号 —— 那些是留给老师复盘的，这一页不出现。

   星级的定义以学期规则为准，前端不自己算：
     · 0 星（未检测）不画星星，只显示「未检测」；
     · 星级只升不降，所以这里只读不算。
   ═══════════════════════════════════════════════════════════ */

import { $, el, renderInline } from "./ui.js";
import { fetchLessonReport, STAR_LABELS, REPORT_WEAK_STARS } from "./api.js";
import { labelOf } from "./phases.js";

export function createView(ctx) {

  var loading = $("report-loading");
  var errorBox = $("report-error");
  var errorText = $("report-error-text");
  var emptyBox = $("report-empty");
  var content = $("report-content");
  var headline = $("report-headline");
  var headlineMinutes = $("report-minutes");
  var headlineKpCount = $("report-kp-count");
  var headlineStrongCount = $("report-strong-count");
  var kpList = $("report-kps");
  var stageList = $("report-stages");
  var stageCard = $("report-stage-card");
  var adviceList = $("report-advice");

  /* 每次 enter 都会 +1。请求回来时对不上就丢弃 ——
     renderRoute 在 hash 变化时都会调 enter，来回切页时会有竞态。 */
  var requestSeq = 0;
  /* 同一节课重复进入直接复用，避免闪一下载入中 */
  var loadedLessonId = null;
  var loadedReport = null;

  /* ── 四个状态互斥 ──────────────────────────────────────── */

  function showState(name) {
    loading.hidden = name !== "loading";
    errorBox.hidden = name !== "error";
    emptyBox.hidden = name !== "empty";
    content.hidden = name !== "content";
  }

  /* ── 渲染 ──────────────────────────────────────────────── */

  function formatMinutes(value) {
    var n = Number(value);
    if (!isFinite(n)) return "–";
    var rounded = Math.round(n * 10) / 10;
    return String(rounded);
  }

  /* 0 星不画星星 —— 权威规则要求「未检测」而不是五颗空星 */
  function renderStars(stars) {
    var wrap = el("span", "report__stars");
    var value = Number(stars) || 0;

    if (value <= 0) {
      wrap.classList.add("report__stars--none");
      wrap.setAttribute("role", "img");
      wrap.setAttribute("aria-label", "未检测");
      wrap.appendChild(el("span", "report__stars-none", "未检测"));
      return wrap;
    }

    wrap.setAttribute("role", "img");
    wrap.setAttribute("aria-label", value + " 星，共 5 星");
    for (var i = 1; i <= 5; i++) {
      var star = el("span", i <= value ? "report__star is-on" : "report__star", "★");
      star.setAttribute("aria-hidden", "true");
      wrap.appendChild(star);
    }
    return wrap;
  }

  /* 标签优先查本地表：后端 STAR_STATUS 只有 1–4 星，
     5 星会被它报成「未检测」。查不到再用后端给的那份。 */
  function statusOf(item) {
    var stars = Number(item.stars) || 0;
    return STAR_LABELS[stars] || item.status || STAR_LABELS[0];
  }

  function renderKnowledgePoints(points) {
    kpList.replaceChildren();
    points.forEach(function (item, i) {
      var row = el("li", "report__kp");
      if (!Number(item.stars)) row.classList.add("report__kp--untouched");

      row.appendChild(el("span", "report__kp-num", String(i + 1)));
      row.appendChild(el("span", "report__kp-name", item.title || item.kp_id || "知识点"));
      row.appendChild(renderStars(item.stars));
      row.appendChild(el("span", "report__kp-status", statusOf(item)));

      kpList.appendChild(row);
    });
  }

  function renderStages(snapshots) {
    stageList.replaceChildren();
    if (!snapshots.length) {
      stageCard.hidden = true;
      return;
    }
    stageCard.hidden = false;

    snapshots.forEach(function (snap) {
      var row = el("li", "report__stage");

      var name = labelOf(snap.stage) || snap.stage || "阶段";
      row.appendChild(el("span", "report__stage-name", name));
      row.appendChild(el("span", "report__stage-time",
        formatMinutes(snap.stage_elapsed_minutes) + " 分钟"));

      /* targets_* 里是 KP-xxx 内部编号，只数个数、不显示内容 */
      var closed = (snap.targets_closed || []).length;
      var open = (snap.targets_open || []).length;
      row.appendChild(el("span", "report__stage-targets",
        closed + " 个目标已达成 · " + open + " 个待补"));

      stageList.appendChild(row);
    });
  }

  function renderAdvice(points) {
    adviceList.replaceChildren();
    var weak = points.filter(function (item) {
      return (Number(item.stars) || 0) <= REPORT_WEAK_STARS;
    });

    if (!weak.length) {
      var good = el("li", "report__advice report__advice--good");
      good.textContent = "全部知识点都达到理解线以上，可以做进阶练习了。";
      adviceList.appendChild(good);
      return;
    }

    weak.forEach(function (item) {
      var stars = Number(item.stars) || 0;
      var mark = stars > 0 ? new Array(stars + 1).join("★") : "0 星";
      var row = el("li", "report__advice");
      /* 先转义再解析 **粗体**，走 ui.js 的 renderInline */
      row.innerHTML = renderInline(
        "**" + (item.title || item.kp_id) + "**（" + mark + "）：" +
        "课上未达到理解线，建议先回到对应片段重听。"
      );
      adviceList.appendChild(row);
    });
  }

  function render(report) {
    var points = report.knowledge_points || [];
    var snapshots = report.stage_snapshots || [];

    /* knowledge_points 为空 = 这节课没有产生任何掌握记录 */
    if (!points.length && !snapshots.length) {
      showState("empty");
      return;
    }

    var lesson = ctx.getLesson();
    headline.textContent = (lesson && lesson.title) || "本节课";

    headlineMinutes.textContent = formatMinutes(report.lesson_elapsed_minutes);
    headlineKpCount.textContent = String(points.length);
    headlineStrongCount.textContent = String(points.filter(function (item) {
      return (Number(item.stars) || 0) >= 4;
    }).length);

    renderKnowledgePoints(points);
    renderStages(snapshots);
    renderAdvice(points);
    showState("content");
  }

  /* ── 取数 ──────────────────────────────────────────────── */

  function load() {
    var seq = ++requestSeq;
    var lessonId = ctx.lessonId;
    showState("loading");

    fetchLessonReport(ctx.sessionId, lessonId).then(function (report) {
      if (seq !== requestSeq) return;   /* 期间又切走了，丢弃这次结果 */
      loadedLessonId = lessonId;
      loadedReport = report;
      render(report);
    }).catch(function (err) {
      if (seq !== requestSeq) return;
      loadedLessonId = null;
      loadedReport = null;
      errorText.textContent = "学习报告加载失败：" + err.message;
      showState("error");
      ctx.toast("学习报告加载失败：" + err.message);
    });
  }

  return {
    mount: function () {
      $("review-replay").addEventListener("click", function () {
        location.hash = ctx.getReplayHash();
      });
      $("report-retry").addEventListener("click", function () {
        loadedLessonId = null;
        loadedReport = null;
        load();
      });
    },

    enter: function () {
      if (ctx.lessonId === loadedLessonId && loadedReport) {
        /* 命中缓存也要把序号推一格：否则「A → B → 回 A」时，
           B 那次还在路上的请求回来会盖掉 A 的报告 */
        requestSeq++;
        render(loadedReport);
        return;
      }
      load();
    },

    leave: function () {
      /* 让还没回来的请求作废。app.js 目前不调 leave，
         留在这里是为了满足视图契约，也免得将来接上时踩坑。 */
      requestSeq++;
    }
  };
}
