/* ═══════════════════════════════════════════════════════════
   AI 学习空间 —— 编排层
   ├─ 路由：课程 / 周次 / 课时 / 课堂 / 课后
   └─ 界面跟随后端的 host_phase（见 ORCHESTRATOR.md）

   前端不决定演到哪一幕。每次拿到后端响应就读 host_phase，
   变了才切界面。所有界面的真值源在后端。

   可选课程与已开放周次由课程目录返回；未来由后端提供真值。
   ═══════════════════════════════════════════════════════════ */

import { $, visibleRoot, showToast } from "./ui.js";

import {
  fetchLesson, fetchStudentCourses, startSession,
  fetchSessionState, fetchSessionMessages, stopSession
} from "./api.js";
import { uiOf, labelOf, isKnown } from "./phases.js";
import { createStage as createClassStage } from "./stage-class.js";
import { createView as createReviewView } from "./view-review.js";
import { createStage as createSummaryStage } from "./stage-summary.js";
import { createStage as createReflectStage } from "./stage-reflect.js";
import { createStage as createDiscussStage } from "./stage-discuss.js";
import { createStage as createDoneStage } from "./stage-done.js";


/* ═══════════════════════════════════════════════════════════
   会话与课时
   ═══════════════════════════════════════════════════════════ */

/* 刷新时恢复正在进行的课堂；已经结束或长期中断的课堂自动换新会话。 */
var SESSION_KEY = "ai-learn.sessionId.";

function createSessionId() {
  return (window.crypto && crypto.randomUUID)
    ? crypto.randomUUID()
    : "s-" + Date.now() + "-" + Math.random().toString(16).slice(2);
}

function saveSessionId(lessonId, value) {
  try { localStorage.setItem(SESSION_KEY + lessonId, value); } catch (e) { /* 忽略 */ }
  return value;
}

function loadSessionId(lessonId) {
  try {
    var saved = localStorage.getItem(SESSION_KEY + lessonId);
    if (saved) return saved;
  } catch (e) { /* 隐私模式下不可用 */ }
  var fresh = createSessionId();
  saveSessionId(lessonId, fresh);
  return fresh;
}

function renewSessionId(lessonId) {
  return saveSessionId(lessonId, createSessionId());
}

/* 「这一页是刚打开的，还是刷新出来的？」

   用来区分老师关掉命令行窗口重新启动（= 该从头上新课），
   和学生按了下 F5（= 不该把上到一半的课清掉）。

   **不能靠时间判断**：关窗再启动通常也在两分钟以内，和刷新没差别。
   sessionStorage 正好是那个中介 —— 它能挺过 F5，但关掉标签页/窗口就没了。 */
var continuedPageSession = (function () {
  try {
    if (window.sessionStorage.getItem("ai-learn.page-open")) return true;
    window.sessionStorage.setItem("ai-learn.page-open", "1");
    return false;
  } catch (e) {
    // 隐私模式读不到 sessionStorage —— 保守当成刷新，宁可留着课也别误清
    return true;
  }
})();

function shouldRenewSession(state) {
  if (!state || state.status === "ended") return true;
  // 没在上课（idle）：不用换，也顺带避开"刚建好的新会话又被换掉"
  if (state.status !== "running") return false;
  // 正在上课 + 这一页是新开的窗口 → 新的一节课
  if (!continuedPageSession) return true;
  if (!state.updated_at) return false;
  var updated = Date.parse(state.updated_at);
  return Number.isFinite(updated) && Date.now() - updated > 2 * 60 * 1000;
}

var sessionId = "";
var currentCourseId = "";
var currentLessonId = "";
var lesson = null;
var courses = null;
var catalogPromise = null;

/* 后端当前说的那一幕。null 表示还没跟后端对过话 */
var hostPhase = null;
var messageCursor = 0;
var pollTimer = null;

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

function lessonEndedFlag(lessonId) {
  try { return localStorage.getItem("ai-learn.lessonEnded." + lessonId) === "1"; }
  catch (e) { return false; }
}

function markLessonEnded(lessonId) {
  if (!lessonId) return;
  try { localStorage.setItem("ai-learn.lessonEnded." + lessonId, "1"); } catch (e) {}
}

/* 平台态入口标识：与 api.js 的 launchToken() 同源（该函数未导出） */
function isPlatformEntry() {
  try {
    return Boolean(window.__studentLaunchToken ||
      (window.sessionStorage && window.sessionStorage.getItem("__launch_token")));
  } catch (e) { return Boolean(window.__studentLaunchToken); }
}

/* 课程列表的返回：平台态回平台「学生首页」（/student），
   独立态才回到学生端内置课程列表。 */
function exitToCourses() {
  if (isPlatformEntry()) {
    window.location.assign("/student");
    return;
  }
  go("#");
}

function lessonDestination(item) {
  return (item && item.status === "completed") || lessonEndedFlag(item && item.lessonId)
    ? "review" : "class";
}

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
    sessionId = loadSessionId(item.lessonId);
    lesson = null;
    hostPhase = null;
    messageCursor = 0;
    resetClassroom();
  }
  $("hub-title").textContent = course.name + " · 第 " + item.week + " 周 · " + item.title;
  $("hub").querySelector(".hub__grid").classList.add("hub__grid--single");
  document.querySelectorAll("#hub [data-goto]").forEach(function (card) {
    card.hidden = card.dataset.goto !== lessonDestination(item);
  });
  $("review-title").textContent = course.name + " · " + item.title + " · 课后";
  /* 课后页的报告内容由 view-review.js 在 enter() 时填 */
}

var replayRouteActive = false;
var replayRouteRequest = 0;

function renderRoute() {
  var route = parseHash();
  replayRouteRequest++;
  if (replayRouteActive && classStage) classStage.leave();
  replayRouteActive = false;
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
    if ((route.name === "class" || route.name === "review") && route.name !== lessonDestination(item)) {
      location.replace(lessonHash(course.courseId, item.lessonId));
      return;
    }
    if (route.name === "lesson") { showView(VIEWS.lesson); return; }
    if (route.name === "class") { openLessonRoute(); return; }
    if (route.name === "review") { showView(VIEWS.review); reviewView.enter(); return; }
    if (route.name === "replay" && lessonDestination(item) === "review") { openReplayRoute(); return; }
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
    /* 后端每轮返回后统一交给这里 —— 「完全跟随」的落点 */
    applyServerTurn: applyServerTurn,
    /* POST 响应里的回复是否已被轮询链路投递过。回复是本轮最后一条消息，
       seq = total-1；轮询若已带到它，messageCursor 就已越过该 seq。
       与 pollSession 的 seq 过滤配对，堵住「POST 响应 vs 在飞轮询」双投递。 */
    replySeenByPoll: function (res) {
      return typeof res.total === "number" && res.total - 1 < messageCursor;
    },
    /* 各阶段模块更新页头状态（视频这类子状态用） */
    setStatus: setStatus,
    /* 课堂内部的局部切换（对话 ⇄ 视频），不经后端 */
    showStage: setStage,
    toast: showToast,
    goHome: function () { go(lessonHash(currentCourseId, currentLessonId)); },
    getReviewHash: function () { return partHash("review"); },
    getReplayHash: function () { return partHash("replay"); }
  };
}

/* 立即切换界面。只改显示，不碰任何进度概念 */
function setStage(name, turn) {
  if (!PANE[name]) return;
  currentStage = name;

  Object.keys(PANE).forEach(function (key) {
    var node = $(PANE[key]);
    if (node) node.hidden = key !== name;
  });

  /* 先按当前 host_phase 给个默认状态，owner.enter 可以覆盖成子状态 */
  setStatus(hostPhase ? labelOf(hostPhase) : "");

  var owner = owners[name];
  if (owner && owner.enter) owner.enter(name, turn);
}

/* 后端每轮返回后统一处理。读 host_phase，变了才切界面。
   切幕由后端的 judge_advance 决定，前端不参与判断。 */
function applyServerTurn(res) {
  if (parseHash().name === "replay") return;
  if (!res || !res.hostPhase) return;
  if (typeof res.total === "number") messageCursor = Math.max(messageCursor, res.total);

  var phase = res.hostPhase;

  if (!isKnown(phase)) {
    console.warn("[app] 后端下发了不认识的 host_phase，已忽略：" + phase);
    return;
  }

  if (phase === hostPhase) return;      /* 没变，什么都不做 */

  hostPhase = phase;
  if (phase === "ending") {
    markLessonEnded(currentLessonId);
    var course = courseById(currentCourseId);
    var completedLesson = course && course.lessons.find(function (item) { return item.lessonId === currentLessonId; });
    if (completedLesson) completedLesson.status = "completed";
  }
  setStatus(labelOf(phase));

  var target = uiOf(phase);
  if (!target) return;

  /* 已经在目标界面了（比如视频是 guided_learning 的内部状态），
     只更新状态文字，别把学生正在看的视频打断 */
  if (target === currentStage) return;
  if (phase === "guided_learning" && currentStage === "video") return;

  setStage(target, res);
}

function deliverServerMessage(message) {
  if (!message || message.role !== "teacher" || !message.text) return;
  var owner = owners[currentStage];
  if (owner && owner.receiveMessage) owner.receiveMessage(message.text);
}

function pollSession() {
  var route = parseHash();
  if (route.name !== "class" || !sessionId) return;
  Promise.all([
    fetchSessionState(sessionId),
    fetchSessionMessages(sessionId, messageCursor)
  ]).then(function (values) {
    var state = values[0];
    var feed = values[1];
    applyServerTurn(state);
    /* seq 去重：POST 响应路径可能已把最新回复渲染并推进了 messageCursor，
       这里按投递时刻的 cursor 过滤，跳过已覆盖的消息——否则同一条回复
       会被两条链路各显示一次（用户看到 AI 连发两条相同消息）。 */
    (feed.messages || []).forEach(function (message) {
      if (typeof message.seq === "number" && message.seq < messageCursor) return;
      deliverServerMessage(message);
    });
    messageCursor = Math.max(messageCursor, feed.total || messageCursor);
  }).catch(function (error) {
    if (error.status !== 404) console.warn("课堂同步失败", error);
  });
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(pollSession, 2000);
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
  currentStage = "idle";
}


/* ═══════════════════════════════════════════════════════════
   进入课堂
   ═══════════════════════════════════════════════════════════ */

function openReplayRoute() {
  replayRouteActive = true;
  var request = replayRouteRequest;
  showView(VIEWS.class);
  setStage("video");
  setStatus("课程回放");
  $("btn-skip-video").hidden = true;
  $("btn-exit-replay").hidden = false;
  $("video-player-status").textContent = "正在加载课程…";
  var requestedHash = location.hash;
  var requestedLessonId = currentLessonId;
  fetchLesson(requestedLessonId).then(function (data) {
    if (request !== replayRouteRequest || location.hash !== requestedHash) return;
    lesson = data;
    $("class-title").textContent = data.title + " · 回放";
    classStage.startReplay();
  }).catch(function (err) {
    if (request !== replayRouteRequest || location.hash !== requestedHash) return;
    $("video-player-status").textContent = "课程加载失败：" + err.message;
  });
}

function openLessonRoute() {
  showView(VIEWS.class);

  if (lesson) {
    if (hostPhase === "ending") {
      sessionId = renewSessionId(currentLessonId);
      hostPhase = null;
      messageCursor = 0;
      resetClassroom();
      lesson = null;
      openLessonRoute();
      return;
    }
    /* 再进来时保留进度，只恢复所处阶段 */
    setStage(currentStage);
    $("btn-start").disabled = false;
    return;
  }

  /* 先把「课前」摆出来，课程信息到了再填 */
  setStage("idle");
  $("btn-start").disabled = true;   /* 课程没到位不让开课 */

  var requestedLessonId = currentLessonId;
  Promise.all([
    fetchLesson(requestedLessonId),
    fetchSessionState(sessionId).catch(function (error) {
      if (error.status !== 404) throw error;
      return startSession({ sessionId: sessionId, lessonId: requestedLessonId });
    }).then(function (state) {
      if (!shouldRenewSession(state)) return state;
      // 换新会话之前先把旧的停掉：后端为它复活的心跳线程否则会一直跑到下课，
      // 在后台把这场"没人上的课"的学情写进这个学生的档案。
      stopSession(sessionId).catch(function () { /* 停不掉也别挡住上课 */ });
      sessionId = renewSessionId(requestedLessonId);
      hostPhase = null;
      messageCursor = 0;
      resetClassroom();
      return startSession({ sessionId: sessionId, lessonId: requestedLessonId });
    })
  ]).then(function (values) {
    var data = values[0];
    var session = values[1];
    if (currentLessonId !== requestedLessonId) return;
    lesson = data;
    classStage.renderLesson(data);
    $("class-title").textContent = data.chapter + " " + data.title;
    $("done-sub").textContent = data.course + " · " + data.chapter + " " + data.title;
    applyServerTurn(session);
    $("btn-start").disabled = session.status !== "idle";
    startPolling();
    pollSession();
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
    if (btn.dataset.back === "courses") { exitToCourses(); return; }
    go(lessonHash(currentCourseId, currentLessonId));
  });
});

/* Esc 等同于返回，但课堂里不生效 —— 课堂中不允许退出 */
document.addEventListener("keydown", function (e) {
  if (e.key !== "Escape") return;
  var route = parseHash();
  if (!route.name || route.name === "class") return;
  if (route.name === "course") { exitToCourses(); return; }
  go(route.name === "lesson" ? courseHash(route.courseId) : lessonHash(currentCourseId, currentLessonId));
});


/* ═══════════════════════════════════════════════════════════
   启动
   ═══════════════════════════════════════════════════════════ */

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
