/* ═══════════════════════════════════════════════════════════
   AI 学习空间 —— 编排层
   ├─ 路由：课程 / 周次 / 课时 / 课堂 / 课后
   └─ 界面跟随后端的 host_phase（见 ORCHESTRATOR.md）

   前端不决定演到哪一幕。每次拿到后端响应就读 host_phase，
   变了才切界面。所有界面的真值源在后端。

   可选课程与已开放周次由课程目录返回；未来由后端提供真值。
   ═══════════════════════════════════════════════════════════ */

import { $, visibleRoot, showToast, appendChatMessage, el, scrollToEnd } from "./ui.js";

import {
  fetchLesson, fetchStudentCourses, startSession,
  fetchSessionState, fetchSessionMessages, sendStudentMessage, sendTeacherAction,
  fetchLessonStars, STAR_LABELS
} from "./api.js";
import { uiOf, labelOf, isKnown } from "./phases.js";
import { createThemeSwitch } from "./theme.js";
import { createStage as createClassStage } from "./stage-class.js";
import { createView as createReviewView } from "./view-review.js";
import { createStage as createSummaryStage } from "./stage-summary.js";
import { createStage as createReflectStage } from "./stage-reflect.js";
import { createStage as createDiscussStage } from "./stage-discuss.js";
import { createStage as createDoneStage } from "./stage-done.js";


/* ═══════════════════════════════════════════════════════════
   会话与课时
   ═══════════════════════════════════════════════════════════ */

/* sessionId 不能每次刷新都换新的 —— 它是后端 checkpointer 的
   thread_id（ORCHESTRATOR.md §7），换了就等于每次刷新后端都当新会话，
   上一轮的状态接不上。所以持久化。 */
var SESSION_KEY = "ai-learn.sessionId.";

function loadSessionId(courseId, lessonId) {
  var storageKey = SESSION_KEY + courseId + "." + lessonId;
  try {
    var saved = localStorage.getItem(storageKey);
    if (saved) return saved;
  } catch (e) { /* 隐私模式下不可用 */ }

  var fresh = (window.crypto && crypto.randomUUID)
    ? crypto.randomUUID()
    : "s-" + Date.now() + "-" + Math.random().toString(16).slice(2);
  try { localStorage.setItem(storageKey, fresh); } catch (e) { /* 忽略 */ }
  return fresh;
}

var sessionId = "";
var currentCourseId = "";
var currentLessonId = "";
var lesson = null;
var courses = null;
var catalogPromise = null;

/* 后端当前说的那一幕。null 表示还没跟后端对过话 */
var hostPhase = null;

/* 后端此刻允许按哪些按钮（available_actions）。前端照它渲染，不自己猜 */
var actions = [];

/* 当前这一幕**之后**还有哪些阶段（后端只算 lesson-plan 里 enabled 的）。
   空数组 = 已经是最后一幕，再点一下就是下课。 */
var remainingStages = [];

/* ── 转录与轮询 ──────────────────────────────────────────
   后端的 s["messages"] 是**唯一**的事实来源：学生发言、AI 回复、
   心跳推的话全在里面。POST 的 reply_text 是同一份数据的副本，
   拿它渲染会让每条消息出现两遍 —— 所以这里只认 /messages。 */
var transcript = [];
var messageCursor = 0;
var pollTimer = null;
var pollBusy = false;

/* 课后演练用：?scale=12 把 45 分钟压成约 4 分钟（后端的 time_scale）。
   正式上课不要带这个参数。 */
var timeScale = (function () {
  var v = parseFloat(new URLSearchParams(location.search).get("scale") || "1");
  return isFinite(v) && v > 0 ? v : 1;
})();

var themeSwitch = null;


/* ═══════════════════════════════════════════════════════════
   路由

   #                                → 我的课程
   #/course/:courseId               → 已开放周次
   #/lesson/:courseId/:lessonId     → 按授课状态显示课堂或课后入口
   #/class/:courseId/:lessonId      → 课堂
   #/review/:courseId/:lessonId     → 课后
   ═══════════════════════════════════════════════════════════ */

var VIEWS = {
  courses: "view-courses",
  weeks: "view-weeks",
  lesson: "hub",
  class: "view-class",
  review: "view-review"
};

function parseHash() {
  var raw = location.hash.replace(/^#\/?/, "");
  if (!raw) return { name: "", courseId: "", lessonId: "" };
  var parts;
  try { parts = raw.split("/").map(decodeURIComponent); }
  catch (e) { return { name: "invalid", courseId: "", lessonId: "" }; }
  return {
    name: parts[0],
    courseId: parts[1] || "",
    lessonId: parts[2] || ""
  };
}

function courseHash(courseId) { return "#/course/" + encodeURIComponent(courseId); }
function lessonHash(courseId, lessonId) {
  return "#/lesson/" + encodeURIComponent(courseId) + "/" + encodeURIComponent(lessonId);
}
function partHash(name) {
  return "#/" + name + "/" + encodeURIComponent(currentCourseId) + "/" + encodeURIComponent(currentLessonId);
}

function go(hash) {
  location.hash = hash;
}

function showView(targetId) {
  switchView(targetId);
}

function switchView(targetId) {
  var target = $(targetId);
  var current = visibleRoot();
  if (!target || current === target) return;

  if (current) current.hidden = true;
  target.hidden = false;

  var heading = target.querySelector("h1, h2");
  if (heading) {
    heading.setAttribute("tabindex", "-1");
    heading.focus({ preventScroll: true });
  }
  window.scrollTo({ top: 0, behavior: "auto" });
}

function loadCourses() {
  if (!catalogPromise) catalogPromise = fetchStudentCourses().then(function (items) {
    courses = Array.isArray(items) ? items : [];
    return courses;
  }).catch(function (error) {
    catalogPromise = null;
    $("course-grid").textContent = "课程加载失败，请刷新页面重试。";
    showToast("课程加载失败：" + error.message);
    throw error;
  });
  return catalogPromise;
}

function courseById(id) { return courses && courses.find(function (item) { return item.courseId === id; }); }
function availableLessons(course) {
  return course.lessons.filter(function (item) { return item.status === "completed" || item.status === "current"; });
}

/* 原来这里有个 lessonDestination()，按「这节课上过没有」决定去课堂还是课后，
   并且拿它挡路由、藏入口卡片。现在去掉了 ——
   后端允许随时开课（/start 幂等，已结束的会话也能恢复），
   到底该显示哪一幕由 /state 的 phase 说了算，前端不必再用猜的状态去挡。
   真正的坑是：只有一节课时，一旦它变成 completed，课堂入口会从界面上消失。 */

function makeNode(tag, className, content) {
  var node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined) node.textContent = content;
  return node;
}

function renderCourses() {
  var grid = $("course-grid");
  grid.replaceChildren();
  if (!courses.length) { grid.textContent = "目前没有已选课程。"; return; }
  courses.forEach(function (course) {
    var available = availableLessons(course);
    var card = makeNode("button", "course-tile");
    card.type = "button";
    card.appendChild(makeNode("span", "course-tile__stripe"));
    var top = makeNode("span", "course-tile__top");
    top.appendChild(makeNode("span", "course-tile__icon", course.icon || "▤"));
    top.appendChild(makeNode("span", "course-tile__badge", "已发布"));
    card.appendChild(top);
    card.appendChild(makeNode("span", "course-tile__title", course.name));
    card.appendChild(makeNode("span", "course-tile__desc", course.summary));
    var stats = makeNode("span", "course-tile__stats");
    stats.appendChild(makeNode("span", "", course.lessons.length + " 个周次"));
    stats.appendChild(makeNode("span", "", available.length + " 节可学"));
    stats.appendChild(makeNode("span", "", "本周第 " + course.currentWeek + " 周"));
    card.appendChild(stats);
    card.appendChild(makeNode("span", "course-tile__action", "进入课程  →"));
    card.addEventListener("click", function () { go(courseHash(course.courseId)); });
    grid.appendChild(card);
  });
}

function renderWeeks(course) {
  $("weeks-course-name").textContent = course.name;
  $("weeks-title").textContent = course.name + " · 选择课时";
  $("weeks-description").textContent = course.summary + " 仅展示已上过和本周要上的课时。";
  var available = availableLessons(course);
  $("weeks-summary").textContent = "当前第 " + course.currentWeek + " 周 · 已开放 " + available.length + " / " + course.lessons.length + " 节课";
  var grid = $("week-grid");
  grid.replaceChildren();
  if (!available.length) { grid.textContent = "本课程暂无已开放课时。"; return; }
  available.forEach(function (item) {
    var card = makeNode("button", "week-tile" + (item.status === "current" ? " week-tile--current" : ""));
    card.type = "button";
    var top = makeNode("span", "week-tile__top");
    top.appendChild(makeNode("span", "week-tile__number", "第 " + item.week + " 周"));
    top.appendChild(makeNode("span", "week-tile__status", item.status === "current" ? "本周课程" : "已上过"));
    card.appendChild(top);
    card.appendChild(makeNode("span", "week-tile__title", item.title));
    card.appendChild(makeNode("span", "week-tile__summary", item.summary));
    card.appendChild(makeNode("span", "week-tile__action", "选择课时  →"));
    card.addEventListener("click", function () { go(lessonHash(course.courseId, item.lessonId)); });
    grid.appendChild(card);
  });
}

function selectLesson(course, item) {
  if (currentLessonId !== item.lessonId || currentCourseId !== course.courseId) {
    currentCourseId = course.courseId;
    currentLessonId = item.lessonId;
    sessionId = loadSessionId(course.courseId, item.lessonId);
    lesson = null;
    hostPhase = null;
    /* 换了课时就是换了一个后端会话，转录和游标都得从头来 */
    stopPolling();
    actions = [];
    remainingStages = [];
    transcript = [];
    messageCursor = 0;
    lastStars = {};
    resetClassroom();
  }
  $("hub-title").textContent = course.name + " · 第 " + item.week + " 周 · " + item.title;
  /* 两张入口卡都留着：课堂随时能进（后端幂等开课），课后报告随时能看
     （没上过就显示空态）。不再按 status 藏其中一张。 */
  $("hub").querySelector(".hub__grid").classList.add("hub__grid--single");
  $("review-title").textContent = course.name + " · " + item.title + " · 课后";
  /* 课后页的报告内容由 view-review.js 在 enter() 时填 */
}

function renderRoute() {
  var route = parseHash();
  if (themeSwitch) themeSwitch.setVisible(!route.name);
  /* 轮询只在课堂里跑；切到课程表 / 课后就停掉，别让它在后台空转 */
  if (route.name !== "class") stopPolling();

  loadCourses().then(function () {
    if (location.hash.replace(/^#$/, "") !== (route.name ? "#/" + [route.name, route.courseId, route.lessonId].filter(Boolean).map(encodeURIComponent).join("/") : "")) return;
    if (!route.name) { renderCourses(); showView(VIEWS.courses); return; }
    var course = courseById(route.courseId);
    if (!course) { location.replace("#"); return; }
    if (route.name === "course") { renderWeeks(course); showView(VIEWS.weeks); return; }
    var item = course.lessons.find(function (entry) { return entry.lessonId === route.lessonId; });
    if (!item || (item.status !== "completed" && item.status !== "current")) {
      location.replace(courseHash(course.courseId));
      showToast("该课时尚未开放");
      return;
    }
    selectLesson(course, item);
    if (route.name === "lesson") { showView(VIEWS.lesson); return; }
    if (route.name === "class") { openLessonRoute(); return; }
    if (route.name === "review") { showView(VIEWS.review); reviewView.enter(); return; }
    location.replace("#");
  }).catch(function () {});
}


/* ═══════════════════════════════════════════════════════════
   课堂界面

   界面不自己排顺序 —— 后端说 host_phase 是哪一个，就显示对应界面。
   唯一的例外是 guided_learning 内部还有「对话 / 视频」两段，
   那是前端的局部状态（学生点「播放视频」进入，看完通知后端）。
   ═══════════════════════════════════════════════════════════ */

var PANE = {
  idle: "stage-idle",
  chat: "stage-chat",
  video: "stage-video",
  summary: "stage-summary",
  reflect: "stage-reflect",
  discuss: "stage-discuss",
  done: "stage-done"
};

var currentStage = "idle";

var owners = {};
var classStage = null;    /* 课堂模块实例：idle/chat/video 三个子阶段共用 */
var reviewView = null;    /* 课后（内容待定） */

/* 页头那枚状态胶囊 —— 进度轨删掉后，这是学生判断「现在在哪一步」
   的唯一依据，所以每一幕切换都要更新它。 */
function setStatus(text) {
  var badge = $("class-badge");
  if (!badge) return;
  if (!text) {
    badge.hidden = true;
    return;
  }
  badge.hidden = false;
  badge.textContent = text;
}

function ctxFor() {
  return {
    get sessionId() { return sessionId; },
    get lessonId() { return currentLessonId; },
    getLesson: function () { return lesson; },
    getPhase: function () { return hostPhase; },
    /* 后端此刻允许按哪些按钮（available_actions 原样） */
    getActions: function () { return actions; },

    /* 学生发言。轮询会把回复画出来，调用方不要自己 append ——
       后端的转录只有一份，自己画就重了。 */
    sendMessage: sendMessage,
    /* 老师动作：begin / media_done / next_stage。按不按得动照 available_actions。 */
    teacherAction: teacherAction,

    /* 讲解阶段（视频模式）直接进播放器面板。幂等 */
    enterVideo: function () {
      if (classStage && classStage.enterVideo) classStage.enterVideo();
    },

    /* 各阶段模块更新页头状态（视频这类子状态用） */
    setStatus: setStatus,
    toast: showToast,
    goHome: function () { go(lessonHash(currentCourseId, currentLessonId)); },
    getReviewHash: function () { return partHash("review"); }
  };
}

/* 立即切换界面。只改显示，不碰任何进度概念 */
function setStage(name) {
  if (!PANE[name]) return;
  currentStage = name;

  Object.keys(PANE).forEach(function (key) {
    var node = $(PANE[key]);
    if (node) node.hidden = key !== name;
  });

  /* 先按当前 host_phase 给个默认状态，owner.enter 可以覆盖成子状态 */
  setStatus(hostPhase ? labelOf(hostPhase) : "");

  var owner = owners[name];
  if (owner && owner.enter) owner.enter(name);
}

/* ── 转录 ⇄ 面板 ─────────────────────────────────────────
   后端的转录是**一条线**（学生发言和 AI 回复混在同一个列表里），
   而界面是按阶段分成好几个面板的。所以切面板时把整条转录
   重画进当前面板的 log —— 否则学生切到复述面板就看不到之前说过的话。 */
var LOG_OF_STAGE = {
  chat: "chat-log",
  summary: "summary-log",
  reflect: "reflect-log",
  discuss: "discuss-log"
};

function renderTranscript() {
  var id = LOG_OF_STAGE[currentStage];
  var log = id ? $(id) : null;
  if (!log) return;
  log.replaceChildren();
  transcript.forEach(function (m) {
    appendChatMessage(log, m.role === "student" ? "me" : "ai", m.text);
  });
  if (awaitingReply) appendTypingRow(log);
}

/* 「AI 正在想」的提示。挂在转录末尾而不是单独占一个元素 ——
   轮询会重画整条转录，独立元素会被抹掉。 */
var awaitingReply = false;

function appendTypingRow(log) {
  var row = el("div", "msg msg--ai");
  row.appendChild(el("div", "msg__avatar", "AI"));

  var bubble = el("div", "msg__bubble typing");
  bubble.innerHTML = "<span></span><span></span><span></span>";
  row.appendChild(bubble);

  log.appendChild(row);
  scrollToEnd(log);
}

/* 结束态没有对话区，把老师最后那句收尾发言放进副标题 ——
   比重复课时名有用。 */
function renderDoneRemark() {
  var sub = $("done-sub");
  if (!sub) return;
  for (var i = transcript.length - 1; i >= 0; i--) {
    if (transcript[i].role === "teacher") {
      sub.textContent = transcript[i].text;
      return;
    }
  }
}

/* ── 星级变化提示 ────────────────────────────────────────
   /state 的 stars 只有 KP-xxx 内部编号，规则里明确不许说给学生听；
   所以比的是 /stars 那份带标题的。只在**变化**时提示，进场不刷屏。 */
var lastStars = {};

function notifyStarChanges(points) {
  points.forEach(function (item) {
    var prev = lastStars[item.kp_id];
    if (prev !== undefined && prev !== item.stars) {
      showToast("★ " + (item.title || item.kp_id) + " → " +
        (STAR_LABELS[item.stars] || "未检测"));
    }
    lastStars[item.kp_id] = item.stars;
  });
}

/* ── 老师按钮 ────────────────────────────────────────────
   后端在 available_actions 里说了此刻允许按哪些，前端照着渲染。
   输入框不在这里管 —— 它们是「随时能打字」，禁用逻辑各阶段模块自己管。 */
function renderActions() {
  var beginBtn = $("btn-start");
  if (beginBtn) beginBtn.disabled = actions.indexOf("begin") === -1;

  var videoBtn = $("btn-skip-video");
  if (videoBtn) {
    videoBtn.disabled = actions.indexOf("media_done") === -1 ||
      hostPhase !== "guided_learning" && hostPhase !== "teach";
  }

  /* 「下一环节」按钮的措辞跟着后端说的走：
     remaining_stages 空了就说明这一幕是最后一幕，再点一下就是下课，
     还写「进入下一环节」会让人以为后面还有内容。
     本课 class_discussion 是 enabled:false，所以进了深层探究之后就是「结束课程」。 */
  var canNext = actions.indexOf("next_stage") !== -1;
  var nextLabel = remainingStages.length ? "进入下一环节" : "结束课程";

  ["summary-next", "reflect-next", "discuss-end"].forEach(function (id) {
    var btn = $(id);
    if (btn && !btn.hidden) {
      btn.disabled = !canNext;
      btn.textContent = nextLabel;
    }
  });
}

/* 后端状态落地。phase 变了才切界面 —— 切幕由后端的 judge_advance 决定，
   前端不参与判断。 */
function applySessionState(state) {
  actions = state.available_actions || [];
  remainingStages = state.remaining_stages || [];
  renderActions();

  var phase = state.phase;
  if (!phase) return;
  if (!isKnown(phase)) {
    console.warn("[app] 后端下发了不认识的 phase，已忽略：" + phase);
    return;
  }
  if (phase === hostPhase) return;

  hostPhase = phase;
  setStatus(labelOf(phase));

  var target = uiOf(phase);
  if (!target) return;
  if (target !== currentStage) setStage(target);
  renderTranscript();
  if (phase === "ending") renderDoneRemark();

  /* 讲解阶段是整段视频模式：后端全程静默，界面直接进播放器面板，
     不该再让学生先点一次「开始播放教学视频」。enterVideo 自己幂等。 */
  if (phase === "guided_learning" || phase === "teach") ctx.enterVideo();
}

/* ── 轮询 ────────────────────────────────────────────────
   一次拉三样：状态、新消息、带标题的星级。
   闹网络的时候不弹提示，下一轮自己会补上。 */
var POLL_MS = 2000;

function poll() {
  if (pollBusy || !sessionId) return Promise.resolve();
  pollBusy = true;

  return Promise.all([
    fetchSessionState(sessionId).catch(function () { return null; }),
    fetchSessionMessages(sessionId, messageCursor).catch(function () { return null; }),
    fetchLessonStars(sessionId).catch(function () { return null; })
  ]).then(function (results) {
    var state = results[0], page = results[1], stars = results[2];

    if (state) applySessionState(state);

    if (page && page.messages && page.messages.length) {
      transcript = transcript.concat(page.messages);
      messageCursor = page.total;
      renderTranscript();
      if (hostPhase === "ending") renderDoneRemark();
    }
    if (stars) notifyStarChanges(stars);
  }).catch(function () {
    /* 静默：下一轮再试 */
  }).then(function () {
    pollBusy = false;
  });
}

function startPolling() {
  if (pollTimer) return;
  poll();
  pollTimer = setInterval(poll, POLL_MS);
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

/* ── 发言 / 老师动作 ─────────────────────────────────────
   两者都只是「让后端推进一轮」，推进后立刻拉一次，不用干等 2 秒。
   失败时统一提示，并把 rejection 继续抛给调用方 ——
   调用方需要知道失败好恢复按钮状态，但不必再提示一遍。 */
function describeError(err) {
  if (err && err.status === 409) return "这节课现在不能发言（可能还没开始上课）";
  return (err && err.message) || "操作失败";
}

/* 一次用户动作：发给后端 → 立刻拉一次（不用干等下一个 2 秒）。
   awaitingReply 期间转录末尾挂着打字提示。 */
function withPending(request) {
  awaitingReply = true;
  renderTranscript();

  return request.then(function () {
    return poll();
  }).catch(function (err) {
    showToast(describeError(err));
    throw err;      /* 抛给调用方恢复按钮状态，但不再提示第二遍 */
  }).then(function () {
    awaitingReply = false;
    renderTranscript();
  });
}

function sendMessage(text) {
  if (!sessionId) return Promise.reject(new Error("还没进课堂"));
  return withPending(sendStudentMessage(sessionId, text));
}

function teacherAction(action) {
  if (!sessionId) return Promise.reject(new Error("还没进课堂"));
  return withPending(sendTeacherAction(sessionId, action));
}

/* 去重：chat/video 和 idle 是同一个模块实例 */
function uniqueOwners() {
  var seen = [];
  Object.keys(owners).forEach(function (key) {
    var owner = owners[key];
    if (owner && seen.indexOf(owner) === -1) seen.push(owner);
  });
  return seen;
}

function resetClassroom() {
  uniqueOwners().forEach(function (owner) {
    if (owner.reset) owner.reset();
  });
  /* 转录是四个面板共用的，换课时把每个面板的对话区都清掉 */
  Object.keys(LOG_OF_STAGE).forEach(function (key) {
    var log = $(LOG_OF_STAGE[key]);
    if (log) log.replaceChildren();
  });
  awaitingReply = false;
  currentStage = "idle";
}


/* ═══════════════════════════════════════════════════════════
   进入课堂
   ═══════════════════════════════════════════════════════════ */

function openLessonRoute() {
  showView(VIEWS.class);

  /* 先把界面摆出来，跟后端对上的那一刻再按 phase 纠正 */
  setStage(lesson ? currentStage : "idle");

  var requestedLessonId = currentLessonId;

  /* 跟后端握手。/start 是幂等的：重复进同一节课不会重开，
     已经结束的会话也会把状态原样读回来，所以每次进课堂都可以放心调。 */
  var started = startSession({ sessionId: sessionId, lessonId: requestedLessonId, timeScale: timeScale });
  started
    .then(function () {
      if (currentLessonId !== requestedLessonId) return;
      startPolling();
    })
    .catch(function (err) {
      if (currentLessonId !== requestedLessonId) return;
      showToast("连不上课堂服务：" + err.message);
    });

  if (lesson) return;   /* 课时信息已经有了，不用再取 */

  /* 新课时的会话必须先由 /start 建好，再按该会话读取课时。并发请求会
     偶发让 /lesson 先到达，表现为课程内容串课或首次进入 404。 */
  started.then(function () {
    return fetchLesson(requestedLessonId, sessionId);
  }).then(function (data) {
    if (currentLessonId !== requestedLessonId) return;
    lesson = data;
    classStage.renderLesson(data);
    $("class-title").textContent = data.chapter + " " + data.title;
    $("done-sub").textContent = data.course + " · " + data.chapter + " " + data.title;
    /* #btn-start 能不能按由 renderActions() 照后端的 available_actions 给，
       这里不再手动开关 —— 前端不猜能不能开课 */
  }).catch(function (err) {
    if (currentLessonId !== requestedLessonId) return;
    $("lesson-eyebrow").textContent = "课程";
    $("lesson-title").textContent = "载入失败";
    $("lesson-summary").textContent = err.message;
    $("lesson-note").textContent = "课程信息加载失败，请返回重试";
    showToast("课程载入失败：" + err.message);
  });
}


/* ═══════════════════════════════════════════════════════════
   事件绑定
   ═══════════════════════════════════════════════════════════ */

window.addEventListener("hashchange", renderRoute);

/* 入口的两张卡 */
document.querySelectorAll("[data-goto]").forEach(function (card) {
  card.addEventListener("click", function () {
    go(partHash(card.dataset.goto === "class" ? "class" : "review"));
  });
});

document.querySelectorAll("[data-back]").forEach(function (btn) {
  btn.addEventListener("click", function () {
    go(btn.dataset.back === "courses" ? "#" : lessonHash(currentCourseId, currentLessonId));
  });
});

/* Esc 等同于返回，但课堂里不生效 —— 课堂中不允许退出 */
document.addEventListener("keydown", function (e) {
  if (e.key !== "Escape") return;
  var route = parseHash();
  if (!route.name || route.name === "class") return;
  go(route.name === "course" ? "#" : route.name === "lesson" ? courseHash(route.courseId) : lessonHash(currentCourseId, currentLessonId));
});


/* ═══════════════════════════════════════════════════════════
   启动
   ═══════════════════════════════════════════════════════════ */

themeSwitch = createThemeSwitch();

var hubBack = makeNode("button", "back", "← 返回课时列表");
hubBack.type = "button";
hubBack.addEventListener("click", function () { go(courseHash(currentCourseId)); });
$("hub").insertBefore(hubBack, $("hub").firstChild);

var ctx = ctxFor();

classStage = createClassStage(ctx);
reviewView = createReviewView(ctx);

owners = {
  /* idle / chat / video 是同一个课堂模块的三个子阶段 */
  idle:    classStage,
  chat:    classStage,
  video:   classStage,
  summary: createSummaryStage(ctx),
  reflect: createReflectStage(ctx),
  discuss: createDiscussStage(ctx),
  done:    createDoneStage(ctx),
  review:  reviewView     /* 视图模块，只为统一 mount */
};

/* 每个模块只 mount 一次 */
uniqueOwners().forEach(function (owner) {
  if (owner && owner.mount) owner.mount();
});

/* 路由决定初始视图 */
renderRoute();
