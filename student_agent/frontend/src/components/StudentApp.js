"use client";

import { useEffect, useRef, useState } from "react";
import { platformPlayerAdapter } from "../integration/platform-player-adapter";
import LessonFeedback from "./LessonFeedback";
import LessonProgress, { STAGE_TITLES } from "./LessonProgress";

async function api(path, method = "GET", body) {
  const response = await fetch(`/api${path}`, {
    method, headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.detail || `请求失败 (${response.status})`);
    error.status = response.status;
    throw error;
  }
  if (data.browserSnapshot && data.browserKey) {
    try {
      localStorage.setItem(`student_browser_snapshot:${data.browserKey}`, data.browserSnapshot);
      localStorage.setItem(`student_browser_session:${data.browserKey}`, data.sessionId);
      localStorage.setItem("student_browser_last_key", data.browserKey);
      if (data.browserCourseKey) localStorage.setItem("student_browser_last_course_key", data.browserCourseKey);
    } catch {
      // Learning continues even when this browser blocks local storage.
    }
  }
  return data;
}

function tokenBrowserKey(token) {
  try {
    const encoded = token.split(".")[0].replace(/-/g, "+").replace(/_/g, "/");
    const payload = JSON.parse(atob(encoded.padEnd(Math.ceil(encoded.length / 4) * 4, "=")));
    return payload.uid && payload.cid ? `${payload.uid}:${payload.cid}` : "";
  } catch {
    return "";
  }
}

function snapshotState(snapshot) {
  try {
    const encoded = snapshot.split(".")[0].replace(/-/g, "+").replace(/_/g, "/");
    const bytes = Uint8Array.from(atob(encoded.padEnd(Math.ceil(encoded.length / 4) * 4, "=")), (char) => char.charCodeAt(0));
    return JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    return null;
  }
}

function savedLessonPhase(courseKey, lessonId) {
  if (typeof window === "undefined" || !courseKey) return "";
  try {
    return snapshotState(localStorage.getItem(`student_browser_snapshot:${courseKey}:${lessonId}`))?.phase || "";
  } catch {
    return "";
  }
}

export default function StudentApp() {
  const [courses, setCourses] = useState([]);
  const [course, setCourse] = useState(null);
  const [lesson, setLesson] = useState(null);
  const [phase, setPhase] = useState("loading");
  const [messages, setMessages] = useState([]);
  const [postclassMessages, setPostclassMessages] = useState([]);
  const [postclassStage, setPostclassStage] = useState(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [replyPending, setReplyPending] = useState(false);
  const [error, setError] = useState("");
  const [replayError, setReplayError] = useState("");
  const [replayLoading, setReplayLoading] = useState(false);
  const [videoEnded, setVideoEnded] = useState(false);
  const [preparation, setPreparation] = useState("idle");
  const [preparationError, setPreparationError] = useState("");
  const [preparationRequestId, setPreparationRequestId] = useState("");
  const [platformUrl, setPlatformUrl] = useState("");
  const [feedback, setFeedback] = useState(null);
  const [agentStage, setAgentStage] = useState("");
  const [learningProgress, setLearningProgress] = useState(null);
  const sessionId = useRef("");
  const activeLessonId = useRef(null);
  const browserCourseKey = useRef("");
  const launchToken = useRef("");
  const catalogCourses = useRef(null);
  const playerSlot = useRef(null);
  const chatLog = useRef(null);
  const composerInput = useRef(null);

  function showSession(saved) {
    setReplayError("");
    sessionId.current = saved.sessionId;
    activeLessonId.current = saved.lessonId || null;
    if (saved.browserCourseKey) browserCourseKey.current = saved.browserCourseKey;
    if (!saved.lessonId) catalogCourses.current = saved.courses || [];
    const visibleCourses = catalogCourses.current || saved.courses || [];
    setCourses(visibleCourses);
    setMessages(saved.messages || []);
    setPostclassMessages(saved.postclassMessages || []);
    setPostclassStage(saved.postclassStage || null);
    setFeedback(saved.feedback || null);
    setAgentStage(saved.agentStage || "");
    setLearningProgress(saved.learningProgress || null);
    setPreparation(saved.preparation || "ready");
    setPreparationError(saved.preparationError || "");
    setPreparationRequestId(saved.preparationRequestId || "");
    // The catalog contains summaries only. Restore the active lesson from
    // this session's course, keeping its player URL and classroom binding.
    const restoredCourse = (saved.courses || []).find((item) => item.lessons.some((entry) => entry.id === saved.lessonId));
    const selectedCourse = restoredCourse
      || visibleCourses.find((item) => item.lessons.some((entry) => entry.id === saved.lessonId)) || visibleCourses[0];
    setCourse(selectedCourse || null);
    setLesson(selectedCourse?.lessons.find((entry) => entry.id === saved.lessonId) || null);
    setPhase(saved.phase === "idle" || saved.phase === "courses" ? "lessons" : saved.phase);
  }

  useEffect(() => {
    const url = new URL(window.location.href);
    const freshToken = url.searchParams.get("launch_token");
    const courseKey = (freshToken && tokenBrowserKey(freshToken))
      || localStorage.getItem("student_browser_last_course_key") || "demo";
    browserCourseKey.current = courseKey;
    const token = freshToken || localStorage.getItem(`student_browser_token:${courseKey}`) || "";
    launchToken.current = token;
    if (token) localStorage.setItem(`student_browser_token:${courseKey}`, token);
    const legacySnapshot = localStorage.getItem(`student_browser_snapshot:${courseKey}`);
    if (legacySnapshot) {
      const legacyLessonId = snapshotState(legacySnapshot)?.lessonId;
      if (legacyLessonId) {
        const lessonKey = `${courseKey}:${legacyLessonId}`;
        if (!localStorage.getItem(`student_browser_snapshot:${lessonKey}`)) {
          localStorage.setItem(`student_browser_snapshot:${lessonKey}`, legacySnapshot);
        }
        localStorage.removeItem(`student_browser_snapshot:${courseKey}`);
        localStorage.removeItem(`student_browser_session:${courseKey}`);
        localStorage.setItem("student_browser_last_key", lessonKey);
      }
    }
    if (url.searchParams.has("launch_token")) {
      url.searchParams.delete("launch_token");
      history.replaceState(null, "", url);
    }
    api("/session/platform-entry").catch(() => ({})).then((entry) => {
      setPlatformUrl(entry.platformUrl || "");
      if (!token && !entry.demoEnabled) { setPhase("auth"); return; }
      const resumeKey = freshToken ? `${courseKey}:catalog`
        : localStorage.getItem("student_browser_last_key") || `${courseKey}:catalog`;
      const savedId = localStorage.getItem(`student_browser_session:${resumeKey}`);
      const snapshot = localStorage.getItem(`student_browser_snapshot:${resumeKey}`);
      const resume = freshToken ? Promise.resolve(null) : entry.freshSessionMode && snapshot
        ? api("/session/browser-restore", "POST", { snapshot, launch_token: token }).catch(() => null)
        : savedId ? api(`/session/${savedId}`).catch(() => null) : Promise.resolve(null);
      return resume.then((saved) => {
        if (saved) {
          showSession(saved);
          return;
        }
        if (!freshToken) {
          localStorage.removeItem(`student_browser_snapshot:${resumeKey}`);
          localStorage.removeItem(`student_browser_session:${resumeKey}`);
        }
        return api("/session/start", "POST", { launch_token: token })
          .then((data) => { showSession(data); });
      })
        .catch((err) => { setError(err.message); setPhase("auth"); });
    });
  }, []);

  useEffect(() => {
    if ((phase !== "video" && phase !== "replay") || !lesson || !playerSlot.current) return;
    let handle;
    function playerError(err) {
      if (phase === "replay") {
        setReplayError(err.message);
        setPhase("done");
      } else setError(err.message);
    }
    try {
      handle = platformPlayerAdapter.mount(playerSlot.current, {
        lesson: lesson,
        replay: phase === "replay",
        onEnded: () => setVideoEnded(true),
        onError: playerError,
      });
    } catch (err) { playerError(err); }
    return () => { if (typeof handle === "function") handle(); };
  }, [phase, lesson]);

  useEffect(() => {
    if (phase !== "video" || preparation !== "pending" || busy) return;
    let cancelled = false;
    let timer;
    async function poll() {
      try {
        const current = await api(`/session/${sessionId.current}`);
        if (cancelled) return;
        setPreparation(current.preparation);
        setLearningProgress(current.learningProgress || null);
        setPreparationError(current.preparationError || "");
        setPreparationRequestId(current.preparationRequestId || "");
        if (current.preparation !== "pending") return;
      } catch {
        // A temporary network failure must not interrupt the video.
      }
      if (!cancelled) timer = setTimeout(poll, 2000);
    }
    poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [phase, preparation, busy]);

  useEffect(() => { chatLog.current?.scrollTo({ top: chatLog.current.scrollHeight }); }, [messages, postclassMessages, replyPending, phase]);
  useEffect(() => {
    if (!composerInput.current) return;
    composerInput.current.style.height = "44px";
    composerInput.current.style.height = `${Math.min(132, Math.max(44, composerInput.current.scrollHeight))}px`;
  }, [input]);

  async function chooseLesson(selected) {
    if (busy) return;
    setBusy(true); setError("");
    const lessonKey = `${browserCourseKey.current}:${selected.id}`;
    const snapshot = localStorage.getItem(`student_browser_snapshot:${lessonKey}`);
    try {
      if (snapshot) {
        try {
          const saved = await api("/session/browser-restore", "POST",
            { snapshot, launch_token: launchToken.current });
          if (saved.lessonId === selected.id && saved.phase !== "idle") {
            showSession(saved);
            return;
          }
        } catch (err) {
          if (err.status !== 400 && err.status !== 404) throw err;
          localStorage.removeItem(`student_browser_snapshot:${lessonKey}`);
          localStorage.removeItem(`student_browser_session:${lessonKey}`);
        }
      }
      if (activeLessonId.current) {
        const started = await api("/session/start", "POST", { launch_token: launchToken.current });
        showSession(started);
      }
      setCourse((catalogCourses.current || courses).find((item) => item.lessons.some((entry) => entry.id === selected.id)) || course);
      setLesson(selected);
      setPhase("lesson");
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  async function begin(selected) {
    if (busy) return;
    setBusy(true); setError("");
    setVideoEnded(false);
    setPreparation("pending"); setPreparationError("");
    try {
      const state = await api(`/session/${sessionId.current}/begin/${encodeURIComponent(selected.id)}`, "POST");
      const selectedCourse = (state.courses || []).find((item) => item.lessons.some((candidate) => candidate.id === selected.id));
      const playableLesson = selectedCourse?.lessons.find((candidate) => candidate.id === selected.id);
      if (!playableLesson?.playerUrl) throw new Error("该课时没有可播放的视频");
      sessionId.current = state.sessionId;
      activeLessonId.current = selected.id;
      setCourses(state.courses); setCourse(selectedCourse); setLesson(playableLesson);
      setMessages(state.messages); setPhase(state.phase);
      setPostclassMessages(state.postclassMessages || []);
      setPostclassStage(state.postclassStage || null);
      setFeedback(state.feedback || null);
      setAgentStage(state.agentStage || "");
      setLearningProgress(state.learningProgress || null);
      setPreparation(state.preparation); setPreparationError(state.preparationError || "");
      setPreparationRequestId(state.preparationRequestId || "");
    } catch (err) { setError(err.message); setPhase("lesson"); setPreparation("idle"); }
    finally { setBusy(false); }
  }

  async function retryPreparation() {
    setBusy(true); setError("");
    try {
      const current = await api(`/session/${sessionId.current}/prepare`, "POST");
      setPreparation(current.preparation); setPreparationError(current.preparationError || "");
      setPreparationRequestId(current.preparationRequestId || "");
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  async function goDiscussion() {
    setBusy(true); setError("");
    try {
      const state = await api(`/session/${sessionId.current}/discussion`, "POST");
      setMessages(state.messages); setPhase(state.phase);
      setAgentStage(state.agentStage || "");
      setLearningProgress(state.learningProgress || null);
      setPreparation(state.preparation); setPreparationError(state.preparationError || "");
      setPreparationRequestId(state.preparationRequestId || "");
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  async function send(event) {
    event.preventDefault();
    if (!input.trim() || busy || (phase === "discussion" && agentStage === "wrapup")) return;
    const isPostclass = phase === "postclass";
    const text = input.trim();
    setInput(""); setBusy(true); setReplyPending(true); setError("");
    const setActiveMessages = isPostclass ? setPostclassMessages : setMessages;
    setActiveMessages((current) => [...current, { role: "student", text }]);
    try {
      const route = isPostclass ? "postclass/message" : "message";
      const state = await api(`/session/${sessionId.current}/${route}`, "POST", { text });
      if (isPostclass) {
        setPostclassMessages(state.postclassMessages || []);
        setPostclassStage(state.postclassStage);
        setFeedback(state.feedback);
      } else {
        setMessages(state.messages);
        setAgentStage(state.agentStage || "");
        setLearningProgress(state.learningProgress || null);
      }
    } catch (err) {
      setActiveMessages((current) => current.slice(0, -1));
      setInput(text); setError(err.message);
    } finally { setReplyPending(false); setBusy(false); }
  }

  function handleComposerKeyDown(event) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }

  async function end() {
    setBusy(true); setError("");
    try {
      const state = await api(`/session/${sessionId.current}/end`, "POST");
      setFeedback(state.feedback); setPhase(state.phase);
      setAgentStage(state.agentStage); setLearningProgress(state.learningProgress || null);
    }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  async function openReplay(refresh = false) {
    if (busy) return;
    setBusy(true); setReplayLoading(true); setError(""); setReplayError("");
    try {
      let playableLesson = lesson;
      if (refresh || !playableLesson?.playerUrl) {
        const playback = await api(`/session/${sessionId.current}/playback`, "POST",
          { launch_token: launchToken.current });
        playableLesson = playback.lesson;
        if (playback.courseId !== course?.id || playableLesson?.id !== activeLessonId.current
            || (lesson?.classroomId && playableLesson?.classroomId !== lesson.classroomId)) {
          throw new Error("播放信息与当前课时不匹配，请从平台重新进入课程");
        }
      }
      if (!playableLesson?.playerUrl) throw new Error("本课时暂时没有可播放的视频，请稍后重试或联系教师");
      setLesson(playableLesson); setVideoEnded(false); setPhase("replay");
    } catch (err) { setReplayError(err.message); }
    finally { setBusy(false); setReplayLoading(false); }
  }

  async function openPostclass() {
    setBusy(true); setError("");
    try {
      const state = await api(`/session/${sessionId.current}/postclass/start`, "POST");
      setPostclassMessages(state.postclassMessages || []);
      setPostclassStage(state.postclassStage);
      setPhase("postclass");
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  return <main className="app">
    {phase === "loading" && <section className="view"><p>正在载入课堂…</p></section>}
    {phase === "auth" && <section className="view"><div className="lesson"><h1 className="lesson__title">从课程平台进入课堂</h1><p className="lesson__summary">登录平台后，选择已发布课时开始学习。</p>{error && <p role="alert">{error}</p>}<a className="btn btn--primary" href={`${platformUrl || "http://localhost:8088"}/login`}>前往平台登录</a></div></section>}
    {phase === "error" && <section className="view"><h1>暂时无法进入课堂</h1><p>{error}</p></section>}
    {phase === "lessons" && <section className="view course-browser">
      <header className="course-browser__header">
        <span className="course-browser__brand"><img src="/app/brand-mark.png" alt="" className="course-browser__logo" />AI 学习空间 <span>· 学生端</span></span>
        <a className="back course-browser__home" href={`${platformUrl || "http://localhost:8088"}/student`}>← 返回首页</a>
      </header>
      <div className="course-browser__intro"><p className="course-browser__eyebrow">我的课时</p><h1>{course?.title || "课程"} <span>· 选择课时</span></h1><p>选择已开放的课时，开始学习或回顾课程。</p></div>
      <div className="weeks-summary">已开放 {course?.lessons.length || 0} 节课 · 按教学周次排列</div>
      <div className="week-grid">{course?.lessons.map((item, index) => {
        const isLatest = index === course.lessons.length - 1;
        const savedPhase = savedLessonPhase(browserCourseKey.current, item.id);
        return <button type="button" className={`week-tile${isLatest ? " week-tile--current" : ""}`} key={item.id} disabled={busy} onClick={() => chooseLesson(item)}>
          <span className="week-tile__top"><span className="week-tile__number">第 {item.week} 周 · 第 {item.lessonNumber} 次课</span><span className="week-tile__status">{savedPhase === "done" ? "已完成" : savedPhase ? "继续学习" : isLatest ? "最新开放" : "已开放"}</span></span>
          <span className="week-tile__title">{item.title}</span>
          <span className="week-tile__action">{savedPhase === "done" ? "查看本课反馈 →" : savedPhase ? "继续本课 →" : "选择课时 →"}</span>
        </button>;
      })}</div>
      {!course?.lessons.length && <p>本课程暂无已开放课时。</p>}
    </section>}
    {phase === "lesson" && <section className="view"><header className="view__header"><button className="back" onClick={() => setPhase("lessons")}>← 返回课时</button><h2 className="view__title">{lesson?.title}</h2></header><div className="view__body"><div className="lesson"><p className="lesson__eyebrow">{course?.title} · 第 {lesson?.week} 周</p><h3 className="lesson__title">{lesson?.title}</h3><p className="lesson__summary">{lesson?.summary || "准备好后开始本节课。"}</p><button className="btn btn--primary" onClick={() => begin(lesson)} disabled={busy}>开始或继续上课</button></div></div></section>}
    {(phase === "video" || phase === "discussion" || phase === "done" || phase === "replay" || phase === "postclass") && <section className="view classroom-view"><header className="view__header"><h2 className="view__title">{lesson?.title || "课堂"}</h2><span className="view__badge">{phase === "video" ? "教学视频" : phase === "discussion" ? STAGE_TITLES[agentStage] || "复述与讨论" : phase === "replay" ? "课后回看" : phase === "postclass" ? "课后对话" : "已结束"}</span></header><div className="classroom-layout">
      <LessonProgress phase={phase} agentStage={agentStage} progress={learningProgress} postclassStage={postclassStage} />
      <div className="view__body classroom-content">
      {phase === "video" && <div className="stage stage--video"><div className="video"><div className="video-player-slot" ref={playerSlot} aria-label="视频播放器挂载区域" /><div className="video-player-actions"><p className="video-player-status">{videoEnded ? "视频播放完毕，可以进入复述与讨论。" : "观看视频后，点击按钮进入下一阶段。"}</p><button className="btn btn--primary" type="button" disabled={busy || preparation === "pending"} onClick={preparation === "error" ? retryPreparation : goDiscussion}>{preparation === "pending" ? "复述与讨论准备中…" : preparation === "error" ? "重试准备复述与讨论" : "进入复述与讨论 →"}</button>{preparation === "error" && preparationError && <p role="alert">{preparationError}{preparationRequestId && `（问题编号：${preparationRequestId}）`}</p>}</div></div></div>}
      {phase === "replay" && <div className="stage stage--video"><div className="video"><div className="video-player-slot" ref={playerSlot} aria-label="课后视频播放器" /><div className="video-player-actions"><p className="video-player-status">可以按自己的节奏回看本节课。</p><button className="btn btn--primary" type="button" onClick={() => setPhase("done")}>返回学习反馈</button></div></div></div>}
      {(phase === "discussion" || phase === "postclass") && <div className="stage stage--summary">
        <div className="conversation-panel">
          <div className="conversation-heading">
            <h3 className="new-stage-title">{phase === "postclass"
              ? postclassStage === "remediation" ? "继续未完成的学习" : "全部完成 · 自由提问"
              : "复述与讨论"}</h3>
            <p className="conversation-stage" role="status">{phase === "postclass"
              ? "本次课堂已经结束，课后对话会更新你的学习反馈。"
              : `${STAGE_TITLES[agentStage] || "初始复述"}${learningProgress?.currentPoint ? ` · 当前知识点：${learningProgress.currentPoint}` : ""}`}</p>
          </div>
          <div className="chat conversation-log" role="log" aria-live="polite" ref={chatLog}>
            {(phase === "postclass" ? postclassMessages : messages).map((message, index) => <div className={`msg msg--${message.role === "student" ? "me" : "ai"}`} key={index}>
              {message.role !== "student" && <div className="msg__avatar">AI</div>}
              <div className="msg__bubble">{message.role !== "student" && STAGE_TITLES[message.phase]
                && <span className="msg__stage">{STAGE_TITLES[message.phase]}</span>}{message.text}</div>
            </div>)}
            {replyPending && <div className="msg msg--ai" role="status" aria-label="AI 正在回复"><div className="msg__avatar" aria-hidden="true">AI</div><div className="msg__bubble typing" aria-hidden="true"><span /><span /><span /></div></div>}
          </div>
          {phase === "discussion" && agentStage === "wrapup"
            ? <div className="conversation-complete" role="status"><strong>课堂对话已完成</strong><p>点击下方按钮查看本课反馈。还想继续学习，可以在课后回看视频或与 AI 对话。</p></div>
            : <form className="composer" onSubmit={send}>
              <textarea className="composer__input" ref={composerInput} rows={1} value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={handleComposerKeyDown} placeholder={phase === "postclass" && postclassStage === "open" ? "自由向 AI 提问…" : "说说你的理解，或提出问题…"} aria-label="输入复述或讨论" />
              <button className="composer__send" type="submit" disabled={busy || !input.trim()} aria-label="发送">↑</button>
            </form>}
          <div className="conversation-actions">
            {phase === "postclass" ? <button className="btn btn--primary" type="button" disabled={busy} onClick={() => setPhase("done")}>返回学习反馈</button>
              : <><span className="conversation-end-hint">{agentStage === "wrapup" ? "学习反馈已准备好生成" : "也可以提前结束，未掌握内容会记录在反馈中"}</span><button className={`btn ${agentStage === "wrapup" ? "btn--primary" : "btn--ghost"}`} type="button" disabled={busy} onClick={end}>{busy && !replyPending ? "正在保存…" : agentStage === "wrapup" ? "结束本课并查看反馈" : "提前结束本课"}</button></>}
          </div>
        </div>
      </div>}
      {phase === "done" && <div className="stage stage--done"><div className="done done--feedback"><span className="done__check" aria-hidden="true">✓</span><p>第 {lesson?.week} 周 · 第 {lesson?.lessonNumber} 次课</p><h3 className="done__title">本节课结束</h3><LessonFeedback feedback={feedback} />{replayError && <p className="replay-error" role="alert">暂时无法回看：{replayError}</p>}<div className="postclass-actions"><button className="btn btn--primary" type="button" disabled={busy} onClick={() => openReplay(Boolean(replayError))}>{replayLoading ? "正在获取播放信息…" : replayError ? "重试回看" : "回看视频"}</button><button className="btn btn--primary" type="button" disabled={busy} onClick={openPostclass}>{postclassStage === "open" ? "与 AI 自由提问" : "继续未完成的学习"}</button><button className="btn btn--ghost" type="button" disabled={busy} onClick={() => setPhase("lessons")}>返回课时列表</button><a className="btn btn--ghost" href={`${platformUrl || "http://localhost:8088"}/student`}>返回首页</a></div></div></div>}
    </div></div></section>}
    {error && phase !== "error" && <p className="new-error" role="alert">{error}</p>}
  </main>;
}
