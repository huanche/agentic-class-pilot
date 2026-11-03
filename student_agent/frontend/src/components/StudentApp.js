"use client";

import { useEffect, useRef, useState } from "react";
import { platformPlayerAdapter } from "../integration/platform-player-adapter";
import { createLearningSession } from "../integration/learning-session.mjs";
import LessonFeedback from "./LessonFeedback";
import LessonProgress, { STAGE_TITLES } from "./LessonProgress";

export default function StudentApp() {
  const controllerRef = useRef(null);
  if (!controllerRef.current) controllerRef.current = createLearningSession();
  const controller = controllerRef.current;
  const [learning, setLearning] = useState(() => controller.getView());
  const { courses, course, lesson, postclassStage, preparation, preparationError,
    preparationRequestId, platformUrl, feedback, agentStage, learningProgress,
    flowVersion, progressSummary, videoUpdated, allowedCommands, activityStatus } = learning;
  const phase = learning.screen;
  const busy = learning.busy;
  const dynamicFlow = flowVersion === "dynamic_dialogue_v1";
  const paused = activityStatus === "paused";
  const can = command => !busy && allowedCommands.includes(command);
  const [optimistic, setOptimistic] = useState(null);
  const extra = optimistic && optimistic.sessionId === learning.sessionId && optimistic.screen === phase ? optimistic : null;
  const messages = [...learning.messages, ...(extra && phase === "discussion" && learning.messages.length <= extra.count ? [extra] : [])];
  const postclassMessages = [...learning.postclassMessages, ...(extra && phase === "postclass" && learning.postclassMessages.length <= extra.count ? [extra] : [])];
  const [input, setInput] = useState("");
  const [replyPending, setReplyPending] = useState(false);
  const [localError, setError] = useState("");
  const error = localError || learning.error;
  const [replayError, setReplayError] = useState("");
  const [replayLoading, setReplayLoading] = useState(false);
  const [videoEnded, setVideoEnded] = useState(false);
  const [showResetConfirm, setShowResetConfirm] = useState(false);
  const [showEarlyEndWarning, setShowEarlyEndWarning] = useState(false);
  const [showVideoAdvanceConfirm, setShowVideoAdvanceConfirm] = useState(false);
  const [progressOpen, setProgressOpen] = useState(true);
  const [conversationSize, setConversationSize] = useState(null);
  const playerSlot = useRef(null);
  const chatLog = useRef(null);
  const composerInput = useRef(null);
  const conversationStage = useRef(null);
  const conversationResize = useRef(null);

  useEffect(() => {
    const unsubscribe = controller.subscribe(setLearning);
    controller.initialize({ url: window.location.href,
      replaceUrl: cleanUrl => history.replaceState(null, "", cleanUrl) }).catch(() => {});
    const refresh = () => { if (!document.hidden) controller.refresh(); };
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      unsubscribe();
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [controller]);

  useEffect(() => {
    if (["submit_answer", "postclass_answer", "ask_question"].includes(learning.pendingSubmission?.type)
        && learning.pendingSubmission?.payload?.text) setInput(learning.pendingSubmission.payload.text);
  }, [learning.pendingSubmission?.commandId]);

  useEffect(() => {
    const resetOnViewportResize = () => setConversationSize(null);
    window.addEventListener("resize", resetOnViewportResize);
    return () => window.removeEventListener("resize", resetOnViewportResize);
  }, []);

  function startConversationResize(event, edge) {
    const stage = conversationStage.current;
    const panel = event.currentTarget.parentElement;
    if (!stage || !panel) return;
    const stageRect = stage.getBoundingClientRect();
    const panelRect = panel.getBoundingClientRect();
    const left = panelRect.left - stageRect.left;
    conversationResize.current = { edge, startX: event.clientX, left, right: left + panelRect.width, stageWidth: stageRect.width };
    event.currentTarget.setPointerCapture(event.pointerId);
    event.preventDefault();
  }

  function moveConversationResize(event) {
    const drag = conversationResize.current;
    if (!drag) return;
    const minLeft = window.matchMedia("(max-width: 780px)").matches ? 62 : 320;
    const minWidth = Math.min(360, Math.max(120, drag.stageWidth - minLeft));
    const delta = event.clientX - drag.startX;
    const left = drag.edge === "left"
      ? Math.min(Math.max(drag.left + delta, minLeft), drag.right - minWidth)
      : drag.left;
    const right = drag.edge === "right"
      ? Math.max(Math.min(drag.right + delta, drag.stageWidth), drag.left + minWidth)
      : drag.right;
    setConversationSize({ left, width: right - left });
  }

  useEffect(() => {
    if ((phase !== "video" && phase !== "replay") || !lesson || !playerSlot.current) return;
    let handle;
    function playerError(err) {
      if (phase === "replay") {
        setReplayError(err.message);
        controller.dispatch({ type: "back_feedback" });
      } else setError(err.message);
    }
    try {
      handle = platformPlayerAdapter.mount(playerSlot.current, {
        lesson: lesson,
        replay: phase === "replay",
        onEnded: () => { setVideoEnded(true); setShowVideoAdvanceConfirm(false); },
        onError: playerError,
        // 慢加载提示在播放器真正就绪后自动消失；真实错误不受影响。
        onReady: () => setError((prev) => (prev.includes("仍在加载") ? "" : prev)),
      });
    } catch (err) { playerError(err); }
    return () => { if (typeof handle === "function") handle(); };
  }, [phase, lesson]);

  useEffect(() => { chatLog.current?.scrollTo({ top: chatLog.current.scrollHeight }); }, [messages, postclassMessages, replyPending, phase]);
  useEffect(() => {
    if (!composerInput.current) return;
    composerInput.current.style.height = "44px";
    composerInput.current.style.height = `${Math.min(132, Math.max(44, composerInput.current.scrollHeight))}px`;
  }, [input]);

  async function perform(type, extra = {}) {
    setError("");
    try { return await controller.dispatch({ type, ...extra }); }
    catch (err) { if (controller.getView().error !== err.message) setError(err.message); return null; }
  }

  async function chooseLesson(selected) {
    if (busy) return;
    setError(""); setConversationSize(null); setVideoEnded(false);
    try { await controller.loadLesson(selected); } catch (err) { if (controller.getView().error !== err.message) setError(err.message); }
  }

  async function begin() {
    setVideoEnded(false); setShowVideoAdvanceConfirm(false);
    await perform("begin");
  }

  async function retryPreparation() { await perform("retry_preparation"); }
  async function goDiscussion() { setShowVideoAdvanceConfirm(false); await perform("start_discussion"); }
  function requestDiscussion() {
    if (busy || preparation === "pending") return;
    if (videoEnded) goDiscussion(); else setShowVideoAdvanceConfirm(true);
  }

  async function send(event, type = phase === "postclass" ? "postclass_answer" : "submit_answer") {
    event?.preventDefault();
    if (!input.trim() || busy || (dynamicFlow && !can(type)) || (phase === "discussion" && agentStage === "wrapup")) return;
    const text = input.trim();
    setInput(""); setReplyPending(true); setError("");
    setOptimistic({ role: "student", text, screen: phase, sessionId: learning.sessionId,
      count: phase === "postclass" ? learning.postclassMessages.length : learning.messages.length });
    try { await controller.dispatch({ type, text }); }
    catch (err) { setInput(text); if (controller.getView().error !== err.message) setError(err.message); }
    finally { setOptimistic(null); setReplyPending(false); }
  }

  async function help(text) {
    setReplyPending(true);
    try { await perform("request_help", { text }); }
    finally { setReplyPending(false); }
  }

  function handleComposerKeyDown(event) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }

  async function end() {
    if (await perform("finish")) setShowEarlyEndWarning(false);
  }
  async function openReplay(refresh = false) {
    setReplayLoading(true); setReplayError(""); setError(""); setVideoEnded(false);
    try { await controller.dispatch({ type: "replay", refresh }); }
    catch (err) { setReplayError(err.message); }
    finally { setReplayLoading(false); }
  }
  async function openPostclass() { await perform("continue_after_class"); }
  async function resetLesson() {
    if (await perform("reset_lesson")) setShowResetConfirm(false);
  }

  return <main className="app">
    {videoUpdated && <p role="status">教师已更新本课教学视频，旧学习记录已清除，请从新版视频重新开始学习。</p>}
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
        const savedPhase = controller.lessonPhase(item.id);
        return <button type="button" className={`week-tile${isLatest ? " week-tile--current" : ""}`} key={item.id} disabled={busy} onClick={() => chooseLesson(item)}>
          <span className="week-tile__top"><span className="week-tile__number">第 {item.week} 周 · 第 {item.lessonNumber} 次课</span><span className="week-tile__status">{savedPhase === "done" ? "已完成" : savedPhase ? "继续学习" : isLatest ? "最新开放" : "已开放"}</span></span>
          <span className="week-tile__title">{item.title}</span>
          <span className="week-tile__action">{savedPhase === "done" ? "查看本课反馈 →" : savedPhase ? "继续本课 →" : "选择课时 →"}</span>
        </button>;
      })}</div>
      {!course?.lessons.length && <p>本课程暂无已开放课时。</p>}
    </section>}
    {phase === "lesson" && <section className="view"><header className="view__header"><button className="back" onClick={() => controller.dispatch({ type: "catalog" })}>← 返回课时</button><h2 className="view__title">{lesson?.title}</h2></header><div className="view__body"><div className="lesson"><p className="lesson__eyebrow">{course?.title} · 第 {lesson?.week} 周</p><h3 className="lesson__title">{lesson?.title}</h3><p className="lesson__summary">{lesson?.summary || "准备好后开始本节课。"}</p><button className="btn btn--primary" onClick={() => begin(lesson)} disabled={busy}>开始或继续上课</button></div></div></section>}
    {(phase === "video" || phase === "discussion" || phase === "done" || phase === "replay" || phase === "postclass") && <section className="view classroom-view"><header className="view__header"><h2 className="view__title">{lesson?.title || "课堂"}</h2><span className="view__badge">{phase === "video" ? "教学视频" : phase === "discussion" ? STAGE_TITLES[agentStage] || "复述与讨论" : phase === "replay" ? "课后回看" : phase === "postclass" ? "课后对话" : "已结束"}</span></header><div className={`classroom-layout${progressOpen ? "" : " classroom-layout--progress-hidden"}${phase === "video" || phase === "replay" ? " classroom-layout--video" : ""}${phase === "discussion" || phase === "postclass" ? " classroom-layout--conversation" : ""}`}>
      <nav className="classroom-tools" aria-label="课堂工具"><ul className="classroom-tools__list"><li><button className={`classroom-tools__button${progressOpen ? " is-active" : ""}`} type="button" title={progressOpen ? "收起课堂进程" : "打开课堂进程"} aria-label={progressOpen ? "收起课堂进程" : "打开课堂进程"} aria-controls="lesson-progress-panel" aria-expanded={progressOpen} onClick={() => setProgressOpen((open) => !open)}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="3" /><path d="M9 9h7M9 12h7M9 15h5" /></svg></button></li></ul></nav>
      <div className="classroom-progress-slot" hidden={!progressOpen}>
        <LessonProgress id="lesson-progress-panel" phase={phase} agentStage={agentStage} progress={learningProgress} postclassStage={postclassStage} flowVersion={flowVersion} progressSummary={progressSummary} />
        <button className="classroom-progress-close" type="button" aria-label="收起课堂进程" title="收起课堂进程" onClick={() => setProgressOpen(false)}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m14 5-7 7 7 7" /></svg></button>
      </div>
      <div className="view__body classroom-content">
      {phase === "video" && <div className="stage stage--video"><div className="video"><div className="video-player-slot" ref={playerSlot} aria-label="视频播放器挂载区域" /><div className="video-player-actions"><p className="video-player-status">{videoEnded ? "视频播放完毕，可以进入复述与讨论。" : "视频尚未播放完，提前进入下一阶段时会再次确认。"}</p><button className="btn btn--primary" type="button" disabled={busy || preparation === "pending"} onClick={preparation === "error" ? retryPreparation : requestDiscussion}>{preparation === "pending" ? "复述与讨论准备中…" : preparation === "error" ? "重试准备复述与讨论" : "进入复述与讨论 →"}</button>{preparation === "error" && preparationError && <p role="alert">{preparationError}{preparationRequestId && `（问题编号：${preparationRequestId}）`}</p>}</div>{showVideoAdvanceConfirm && !videoEnded && <div className="video-advance-confirm" role="alert"><strong>视频还没有播放完</strong><p>现在进入复述与讨论会跳过剩余的视频内容，是否确定进入下一阶段？</p><div className="video-advance-confirm__actions"><button className="btn btn--ghost" type="button" disabled={busy} onClick={() => setShowVideoAdvanceConfirm(false)}>继续观看视频</button><button className="btn btn--primary" type="button" disabled={busy} onClick={goDiscussion}>{busy ? "正在进入…" : "确定进入复述与讨论"}</button></div></div>}</div></div>}
      {phase === "replay" && <div className="stage stage--video"><div className="video"><div className="video-player-slot" ref={playerSlot} aria-label="课后视频播放器" /><div className="video-player-actions"><p className="video-player-status">可以按自己的节奏回看本节课。</p><button className="btn btn--primary" type="button" onClick={() => controller.dispatch({ type: "back_feedback" })}>返回学习反馈</button></div></div></div>}
      {(phase === "discussion" || phase === "postclass") && <div className="stage stage--summary" ref={conversationStage}>
        <div className="conversation-panel" style={conversationSize ? { width: conversationSize.width, marginLeft: conversationSize.left, marginRight: 0 } : undefined}>
          <div className="conversation-resize-handle conversation-resize-handle--left" role="separator" aria-label="拖动调整对话框左边缘" aria-orientation="vertical" onPointerDown={(event) => startConversationResize(event, "left")} onPointerMove={moveConversationResize} onPointerUp={() => { conversationResize.current = null; }} onPointerCancel={() => { conversationResize.current = null; }} />
          <div className="conversation-resize-handle conversation-resize-handle--right" role="separator" aria-label="拖动调整对话框右边缘" aria-orientation="vertical" onPointerDown={(event) => startConversationResize(event, "right")} onPointerMove={moveConversationResize} onPointerUp={() => { conversationResize.current = null; }} onPointerCancel={() => { conversationResize.current = null; }} />
          <div className="conversation-heading">
            <h3 className="new-stage-title">{phase === "postclass"
              ? dynamicFlow ? "课后继续交流" : postclassStage === "remediation" ? "继续未完成的学习" : "全部完成 · 自由提问"
              : "复述与讨论"}</h3>
            <p className="conversation-stage" role="status">{phase === "postclass"
              ? "本次课堂已经结束，课后对话会更新你的学习反馈。"
              : `${STAGE_TITLES[agentStage] || "初始复述"}${learningProgress?.currentPoint ? ` · 当前知识点：${learningProgress.currentPoint}` : ""}`}</p>
          </div>
          <div className="chat conversation-log" role="log" aria-live="polite" ref={chatLog}>
            {(phase === "postclass" ? postclassMessages : messages).map((message, index) => <div className={`msg msg--${message.role === "student" ? "me" : "ai"}`} key={message.messageId || index}>
              {message.role !== "student" && <div className="msg__avatar">AI</div>}
              <div className="msg__bubble">{message.role !== "student" && STAGE_TITLES[message.phase]
                && <span className="msg__stage">{STAGE_TITLES[message.phase]}</span>}{message.text}</div>
            </div>)}
            {replyPending && <div className="msg msg--ai" role="status" aria-label="AI 正在回复"><div className="msg__avatar" aria-hidden="true">AI</div><div className="msg__bubble typing" aria-hidden="true"><span /><span /><span /></div></div>}
          </div>
          {(phase === "discussion" || (dynamicFlow && phase === "postclass")) && agentStage === "wrapup"
            ? <div className="conversation-complete" role="status"><strong>课堂对话已完成</strong><p>点击下方按钮查看本课反馈。还想继续学习，可以在课后回看视频或与 AI 对话。</p></div>
            : <form className="composer" onSubmit={event => send(event)}>
              <textarea className="composer__input" ref={composerInput} rows={1} disabled={dynamicFlow && (paused || !can(phase === "postclass" ? "postclass_answer" : "submit_answer"))} value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={handleComposerKeyDown} placeholder={phase === "postclass" && postclassStage === "open" ? "自由向 AI 提问…" : "说说你的理解，或提出问题…"} aria-label="输入复述或讨论" />
              <button className="composer__send" type="submit" disabled={busy || !input.trim() || (dynamicFlow && !can(phase === "postclass" ? "postclass_answer" : "submit_answer"))} aria-label="发送">↑</button>
            </form>}
          {dynamicFlow && <div className="conversation-actions" aria-label="学习操作">
            {allowedCommands.includes("request_help") && <><button className="btn btn--ghost" type="button" disabled={!can("request_help")} onClick={() => help("请给我一个提示。")}>给个提示</button><button className="btn btn--ghost" type="button" disabled={!can("request_help")} onClick={() => help("请举一个例子帮助我理解。")}>举个例子</button></>}
            {allowedCommands.includes("ask_question") && <button className="btn btn--ghost" type="button" disabled={!can("ask_question") || !input.trim()} onClick={event => send(event, "ask_question")}>提出问题</button>}
            {allowedCommands.includes("pause") && <button className="btn btn--ghost" type="button" disabled={!can("pause")} onClick={() => perform("pause")}>暂停学习</button>}
            {allowedCommands.includes("resume_activity") && <button className="btn btn--primary" type="button" disabled={!can("resume_activity")} onClick={() => perform("resume_activity")}>继续学习</button>}
            {paused && <span role="status">学习已暂停，当前任务已保留。</span>}
          </div>}
          <div className="conversation-actions">
            {phase === "postclass" ? <button className="btn btn--primary" type="button" disabled={busy} onClick={() => controller.dispatch({ type: "back_feedback" })}>返回学习反馈</button>
              : dynamicFlow ? <button className="btn btn--primary" type="button" disabled={!can("finish")} onClick={end}>结束本课并查看反馈</button> : <><span className="conversation-end-hint">{agentStage === "wrapup" ? "学习反馈已准备好生成" : "提前结束仅供测试使用"}</span><button className={`btn ${agentStage === "wrapup" ? "btn--primary" : "btn--ghost"}`} type="button" disabled={busy} onClick={agentStage === "wrapup" ? end : () => setShowEarlyEndWarning(true)}>{busy && !replyPending ? "正在保存…" : agentStage === "wrapup" ? "结束本课并查看反馈" : "提前结束本课"}</button></>}
          </div>
          {phase === "discussion" && agentStage !== "wrapup" && showEarlyEndWarning && <div className="early-end-warning" role="alert"><strong>提前结束仅限测试使用</strong><p>学生请勿使用此按钮。确认后将跳过正常学习阶段，直接结束本课；尚未完成的复述和讨论会记录为未完成。</p><div className="early-end-warning__actions"><button className="btn btn--ghost" type="button" disabled={busy} onClick={() => setShowEarlyEndWarning(false)}>取消，继续学习</button><button className="btn btn--reset-confirm" type="button" disabled={busy} onClick={end}>{busy ? "正在结束…" : "确认提前结束（仅测试）"}</button></div></div>}
        </div>
      </div>}
      {phase === "done" && <div className="stage stage--done"><div className="done done--feedback"><span className="done__check" aria-hidden="true">✓</span><p>第 {lesson?.week} 周 · 第 {lesson?.lessonNumber} 次课</p><h3 className="done__title">本节课结束</h3><LessonFeedback feedback={feedback} />
        {messages.length > 0 && <details className="conversation-history">
          <summary>查看历史会话（{messages.length} 条）</summary>
          <div className="chat conversation-log" role="log" aria-label="历史课堂与课后对话">
            {messages.map((message, index) => <div className={`msg msg--${message.role === "student" ? "me" : "ai"}`} key={message.messageId || index}>
              {message.role !== "student" && <div className="msg__avatar">AI</div>}
              <div className="msg__bubble"><span className="msg__stage">{String(message.phase || "").startsWith("postclass-") ? "课后对话" : STAGE_TITLES[message.phase] || "课堂对话"}</span>{message.text}</div>
            </div>)}
          </div>
        </details>}{replayError && <p className="replay-error" role="alert">暂时无法回看：{replayError}</p>}<div className="postclass-actions"><button className="btn btn--primary" type="button" disabled={busy} onClick={() => openReplay(Boolean(replayError))}>{replayLoading ? "正在获取播放信息…" : replayError ? "重试回看" : "回看视频"}</button><button className="btn btn--primary" type="button" disabled={busy} onClick={openPostclass}>{postclassStage === "open" ? "与 AI 自由提问" : "继续未完成的学习"}</button><button className="btn btn--ghost" type="button" disabled={busy} onClick={() => controller.dispatch({ type: "catalog" })}>返回课时列表</button><a className="btn btn--ghost" href={`${platformUrl || "http://localhost:8088"}/student`}>返回首页</a></div><div className="lesson-reset"><button className="btn btn--reset" type="button" disabled={busy} onClick={() => setShowResetConfirm(true)}>重置本课学习进度</button>{showResetConfirm && <div className="lesson-reset__confirm" role="group" aria-label="确认重置本课学习进度"><p>确定重新学习「{lesson?.title}」吗？本课的对话、知识点掌握情况和反馈将被删除，其他课时不受影响。此操作无法撤销。</p><div><button className="btn btn--ghost" type="button" disabled={busy} onClick={() => setShowResetConfirm(false)}>取消</button><button className="btn btn--reset-confirm" type="button" disabled={busy} onClick={resetLesson}>{busy ? "正在重置…" : "确认重置本课"}</button></div></div>}</div></div></div>}
    </div></div></section>}
    {learning.connectionError && !error && <p role="status">连接暂时中断，正在重试同步学习状态。</p>}
    {error && !replayError && phase !== "error" && <p className="new-error" role="alert">{error}</p>}
  </main>;
}
