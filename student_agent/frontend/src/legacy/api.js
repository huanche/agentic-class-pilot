/* 学生端 API：一个 AI 消息入口，阶段由后端会话状态决定。 */

var API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || "").replace(/\/$/, "");

function request(method, url, body) {
  var options = { method: method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  return fetch(API_BASE_URL + url, options).then(async function (res) {
    var data = null;
    try { data = await res.json(); } catch (error) { /* 空响应 */ }
    if (!res.ok) {
      var detail = data && data.detail ? data.detail : "HTTP " + res.status;
      var failure = new Error(detail);
      failure.status = res.status;
      throw failure;
    }
    return data || {};
  });
}

function sessionUrl(sessionId, suffix) {
  return "/api/session/" + encodeURIComponent(sessionId) + (suffix || "");
}

export function normalizeTurn(result) {
  return {
    ok: result.ok !== false,
    /* 只有 /api/session/start 会返回；平台深链靠它拿会话号去拉课程上下文 */
    sessionId: result.session_id || null,
    message: { text: result.reply_text || "", speech: "" },
    hostPhase: result.phase || null,
    phaseName: result.phase_name || "",
    status: result.status,
    currentQuestion: result.current_question || null,
    stars: result.stars || {},
    total: typeof result.total === "number" ? result.total : null,
    availableActions: result.available_actions || []
  };
}

export function fetchStudentCourses() {
  /* 平台态：课程目录来自会话的 learning_context（平台已发布内容），
     不依赖本系统自建的学生账号 cookie —— 平台学生没有这个账号。
     独立态：走 /api/student/courses 的登录学生名单。 */
  if (launchToken()) return fetchSessionCourses(currentSessionId());
  return request("GET", "/api/student/courses").then(function (r) { return r.courses || []; });
}

/* 平台链路专用：课程目录来自会话的 learning_context（平台已发布内容），
   不依赖本系统的学生账号 cookie。独立入口请用上面的 fetchStudentCourses。 */
export function fetchSessionCourses(sessionId) {
  var query = sessionId ? "?sessionId=" + encodeURIComponent(sessionId) : "";
  return request("GET", "/api/session/courses" + query);
}

export function fetchLesson(lessonId) {
  /* 两条链路的数据来源不同，必须分开取：
       平台态 → /api/session/lesson 读平台下发的 learning_context，
                返回的就是**裸课时对象**（含 classroomId / playerUrl / segments）
       独立态 → /api/lesson 读本地课时文件，外面包了一层 {lesson: ...}
     两者的返回值形状一致（都是课时对象），app.js 直接用 data.chapter/title。 */
  if (launchToken()) {
    var sid = currentSessionId();
    var query = "?lessonId=" + encodeURIComponent(lessonId || "") +
      (sid ? "&sessionId=" + encodeURIComponent(sid) : "");
    return request("GET", "/api/session/lesson" + query);
  }
  return request("GET", "/api/lesson?lessonId=" + encodeURIComponent(lessonId))
    .then(function (r) { return r.lesson; });
}

export function fetchLessonVideo(lessonId) {
  /* 平台态没有"单个视频地址"这个东西：播放器是嵌进来的教师端课堂 iframe，
     由 mount context 里的 classroomId / lesson.playerUrl 决定。
     这里必须直接返回 null —— 不能去调独立态的 /api/lesson/video，那边没有
     平台课时会 404，而 stage-class 的 startVideo 是 .then(挂播放器).catch(报错)，
     一个 404 就会把整个挂载流程中断掉，播放器永远出不来。 */
  if (launchToken()) return Promise.resolve(null);
  return request("GET", "/api/lesson/video?lessonId=" + encodeURIComponent(lessonId))
    .then(function (r) { return r.video || null; });
}

/* 平台深链令牌。StudentApp 读到 URL 上的 launch_token 后写进这两处之一
   （window 全局 + sessionStorage 桥，见那边的注释）。
   有令牌 = 平台态：身份、课程、课时全部以平台下发的 learning_context 为准。 */
function launchToken() {
  try {
    return window.__studentLaunchToken || sessionStorage.getItem("__launch_token") || "";
  } catch (error) {
    return window.__studentLaunchToken || "";
  }
}

/* 平台会话号（StudentApp 深链时写入）。平台专用端点靠它定位
   learning_context —— 一个课程可能有多个进行中的会话。 */
function currentSessionId() {
  try { return sessionStorage.getItem("__studentSessionId") || ""; } catch (error) { return ""; }
}

/* 登录后的学生身份（StudentLogin 存进 localStorage）。
   取不到就沿用旧的兜底值 —— 后端没配名单时登录页本来就会放行。 */
function currentStudentId() {
  try {
    var raw = window.localStorage.getItem("ai-learn.student");
    var student = raw ? JSON.parse(raw) : null;
    return student && student.studentId ? student.studentId : "";
  } catch (error) {
    return "";
  }
}

export function startSession(payload) {
  return request("POST", "/api/session/start", {
    session_id: payload.sessionId,
    student_id: payload.studentId || currentStudentId() || "student-001",
    lesson_id: payload.lessonId || "",
    time_scale: payload.timeScale || 1,
    /* 平台深链：带上 launch token 时后端以令牌为准，上面的 student_id 会被忽略 */
    launch_token: launchToken() || undefined
  }).then(normalizeTurn);
}

export function beginSession(sessionId) {
  return request("POST", sessionUrl(sessionId, "/begin")).then(normalizeTurn);
}

export function sendMessage(sessionId, text) {
  return request("POST", sessionUrl(sessionId, "/message"), { text: text })
    .then(normalizeTurn);
}

export function notifyMediaDone(sessionId, sceneId, eventId) {
  /* 带上场景/事件 id：平台侧按 (session, scene) 幂等记播放进度。
     缺省时不传，后端退化成"整段完成"（"__complete__"）。 */
  return request("POST", sessionUrl(sessionId, "/media/done"), {
    scene_id: sceneId || undefined,
    event_id: eventId || undefined
  }).then(normalizeTurn);
}

export function advanceStage(sessionId) {
  return request("POST", sessionUrl(sessionId, "/stage/next"), {})
    .then(normalizeTurn);
}

export function fetchSessionState(sessionId) {
  return request("GET", sessionUrl(sessionId, "/state")).then(function (state) {
    return {
      ...state,
      hostPhase: state.phase,
      currentQuestion: state.current_question,
      availableActions: state.available_actions || []
    };
  });
}

export function fetchSessionMessages(sessionId, since) {
  return request("GET", sessionUrl(sessionId, "/messages?since=" + (since || 0)));
}

/* 0–5 星标签。口径取自后端 rules/interaction/MASTERY-STAR-RULES.md，
   那份文件自称「唯一权威规则，任何页面不得另算一套」——
   这里不重算星级，只是补一张标签查表：后端决定星级的 STAR_STATUS 缺少
   0 和 5 两个键，5 星会被它报成「未检测」，所以要拿这张表兜底。 */
export var STAR_LABELS = {
  0: "未检测",
  1: "已接触",
  2: "初步理解",
  3: "理解中",
  4: "接近掌握",
  5: "已掌握"
};

/* 后端 md 分支用的「理解线」：星级 <= 2 视为没达标 */
export var REPORT_WEAK_STARS = 2;

/* 停课。换新会话前要先停掉旧的 —— 不然后端为它复活的心跳线程会一直跑到下课，
   在后台把学情写进这个学生的档案里。 */
export function stopSession(sessionId) {
  return request("DELETE", sessionUrl(sessionId));
}

/* 课后学情报告。响应是**裸 JSON，没有 { ok } 信封**（与本文件其它接口不同），
   别去拆 r.report —— request() 直接返回整个响应对象。
   sessionId 用后端自己下发的那个（形如 cls-xxxx，来自 startSession），
   不是 app.js 存在 localStorage 里按课时生成的那个 UUID。
   报告只在课已结束（status === "ended"）后才有内容。
   第二个参数 lessonId 只用于调用方语义，后端按会话取课时，不参与请求。 */
export function fetchLessonReport(sessionId) {
  return request("GET", sessionUrl(sessionId, "/export?fmt=json"));
}
