/* 学生端平台 API：课程、身份和课时都来自平台签发的 launch token。 */

var API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || "").replace(/\/$/, "");

function request(method, url, body) {
  var options = { method: method, headers: {}, credentials: "include" };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  return fetch(API_BASE_URL + url, options).then(async function (res) {
    var data = null;
    try { data = await res.json(); } catch (error) {}
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

function launchToken() {
  try {
    return window.__studentLaunchToken || sessionStorage.getItem("__launch_token") || "";
  } catch (error) {
    return window.__studentLaunchToken || "";
  }
}

function currentSessionId() {
  try { return sessionStorage.getItem("__studentSessionId") || ""; } catch (error) { return ""; }
}

export function normalizeTurn(result) {
  return {
    ok: result.ok !== false,
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
  return fetchSessionCourses(currentSessionId());
}

export function fetchSessionCourses(sessionId) {
  var query = sessionId ? "?sessionId=" + encodeURIComponent(sessionId) : "";
  return request("GET", "/api/session/courses" + query);
}

export function fetchLesson(lessonId) {
  var sid = currentSessionId();
  var query = "?lessonId=" + encodeURIComponent(lessonId || "") +
    (sid ? "&sessionId=" + encodeURIComponent(sid) : "");
  return request("GET", "/api/session/lesson" + query);
}

export function fetchLessonVideo() {
  // 平台课堂由教师端播放器承载，没有学生端本地视频文件。
  return Promise.resolve(null);
}

export function startSession(payload) {
  var token = launchToken();
  if (!token) return Promise.reject(new Error("请从课程平台重新进入课堂"));
  return request("POST", "/api/session/start", {
    session_id: payload.sessionId,
    lesson_id: payload.lessonId || "",
    time_scale: payload.timeScale || 1,
    launch_token: token
  }).then(normalizeTurn);
}

export function beginSession(sessionId) {
  return request("POST", sessionUrl(sessionId, "/begin")).then(normalizeTurn);
}

export function sendMessage(sessionId, text) {
  return request("POST", sessionUrl(sessionId, "/message"), { text: text }).then(normalizeTurn);
}

export function notifyMediaDone(sessionId, sceneId, eventId, final) {
  return request("POST", sessionUrl(sessionId, "/media/done"), {
    scene_id: sceneId || undefined,
    event_id: eventId || undefined,
    final: final !== false
  }).then(normalizeTurn);
}

export function advanceStage(sessionId) {
  return request("POST", sessionUrl(sessionId, "/stage/next"), {}).then(normalizeTurn);
}

export function endLesson(sessionId) {
  return request("POST", sessionUrl(sessionId, "/end"), {}).then(normalizeTurn);
}

export function fetchSessionState(sessionId) {
  return request("GET", sessionUrl(sessionId, "/state")).then(function (state) {
    return { ...state, hostPhase: state.phase, currentQuestion: state.current_question,
      availableActions: state.available_actions || [] };
  });
}

export function fetchSessionMessages(sessionId, since) {
  return request("GET", sessionUrl(sessionId, "/messages?since=" + (since || 0)));
}

export var STAR_LABELS = {
  0: "未检测", 1: "已接触", 2: "初步理解", 3: "理解中", 4: "接近掌握", 5: "已掌握"
};
export var REPORT_WEAK_STARS = 2;

export function stopSession(sessionId) {
  return request("DELETE", sessionUrl(sessionId));
}

export function fetchLessonReport(sessionId) {
  return request("GET", sessionUrl(sessionId, "/export?fmt=json"));
}
