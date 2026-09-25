"use client";

/* 加入课程：输入老师给的课程码。
 *
 * 复用 .login 那套遮罩/卡片样式 —— 两屏视觉语言相同，没必要再写一套。
 * `required` 为真时不显示"稍后再说"（学生一门课都没有，没有退路）。
 */

import { useEffect, useRef, useState } from "react";

export default function StudentEnroll({ required = false, onDone, onSkip }) {
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const inputRef = useRef(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  async function handleSubmit(event) {
    event.preventDefault();
    const value = code.trim();
    if (!value || busy) return;

    setBusy(true);
    setError("");
    try {
      const res = await fetch("/api/student/join", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ code: value }),
      });
      if (!res.ok) {
        let message = "课程码无效，找老师确认一下";
        try {
          const data = await res.json();
          if (data && data.detail) message = data.detail;
        } catch {
          /* 空响应，用默认文案 */
        }
        throw new Error(message);
      }
      const data = await res.json();
      onDone(data.courses || []);
    } catch (err) {
      setError(err && err.message ? err.message : "加入失败，请重试");
      setBusy(false);
      inputRef.current?.focus();
    }
  }

  return (
    <div className="login" role="dialog" aria-modal="true" aria-labelledby="enroll-title">
      <div className="login__backdrop" aria-hidden="true" />

      <form className="login__card" onSubmit={handleSubmit}>
        <span className="login__icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"
               strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 9.5 12 5l9 4.5-9 4.5-9-4.5Z" />
            <path d="M7 12v4.5c0 1.1 2.2 2 5 2s5-.9 5-2V12" />
            <path d="M20 10.5v5" />
          </svg>
        </span>

        <h1 className="login__title" id="enroll-title">加入课程</h1>
        <p className="login__subtitle">输入老师给你的课程码</p>

        <div className="login__field">
          <label className="login__label" htmlFor="enroll-code">课程码</label>
          <input
            id="enroll-code"
            ref={inputRef}
            className="login__input login__input--code"
            value={code}
            onChange={(e) => {
              setCode(e.target.value.toUpperCase());
              if (error) setError("");
            }}
            placeholder="例如 OSK7M3"
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            disabled={busy}
          />
        </div>

        {error ? <p className="login__error" role="alert">{error}</p> : null}

        <button type="submit" className="login__submit" disabled={!code.trim() || busy}>
          {busy ? "正在加入…" : "加入课程"}
        </button>

        {required ? (
          <p className="login__hint">还没有课程码？找任课老师要一个。</p>
        ) : (
          <p className="login__switch">
            <button
              type="button"
              className="login__switch-btn"
              onClick={onSkip}
              disabled={busy}
            >
              稍后再说
            </button>
          </p>
        )}
      </form>
    </div>
  );
}
