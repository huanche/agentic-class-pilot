"use client";

/* 学生端登录 / 注册。
 *
 * 视觉仿平台（SZU-AgentEduPlatform）的访问码弹窗，但按本仓库的写法重做：
 * 这里没有 Tailwind / Framer Motion / lucide，样式全部走 globals.css 的
 * 既有 token，不引新依赖。
 *
 * 语义和平台不同：平台是全站共享一个访问码；这里是**每个学生自己的账号**
 * （学号 + 密码，注册时再填姓名）。校验全在服务端，前端只收表单和存结果。
 */

import { useEffect, useRef, useState } from "react";

export const STUDENT_KEY = "ai-learn.student";

/** 读本地存的学生身份；没有或解析失败返回 null。 */
export function readStoredStudent() {
  if (typeof window === "undefined") return null;
  try {
    return JSON.parse(window.localStorage.getItem(STUDENT_KEY) || "null");
  } catch {
    return null;
  }
}

export function rememberStudent(student) {
  try {
    if (student) window.localStorage.setItem(STUDENT_KEY, JSON.stringify(student));
    else window.localStorage.removeItem(STUDENT_KEY);
  } catch {
    /* 隐私模式写不了 localStorage —— 不影响本次会话 */
  }
}

async function postJson(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let message = "请求失败，请重试";
    try {
      const data = await res.json();
      if (data && data.detail) message = data.detail;
    } catch {
      /* 空响应，用默认文案 */
    }
    throw new Error(message);
  }
  return res.json();
}

export default function StudentLogin({ onDone }) {
  // checking = 正在问后端；form = 待填；submitting = 提交中
  const [phase, setPhase] = useState("checking");
  const [mode, setMode] = useState("login");        // login | register
  const [error, setError] = useState("");
  const [studentNumber, setStudentNumber] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const numberRef = useRef(null);

  useEffect(() => {
    let alive = true;
    fetch("/api/student/session", { credentials: "include" })
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error("HTTP " + res.status))))
      .then((data) => {
        if (!alive) return;
        if (data.authenticated) {
          rememberStudent(data.student);
          return onDone(data.student, data.courses || []);
        }
        setPhase("form");
      })
      .catch(() => {
        if (!alive) return;
        // 后端够不着时不要把人锁在门外 —— 放行，让原本的错误提示去报
        onDone(null, []);
      });
    return () => {
      alive = false;
    };
  }, [onDone]);

  useEffect(() => {
    if (phase === "form") numberRef.current?.focus();
  }, [phase, mode]);

  function switchMode(next) {
    setMode(next);
    setError("");
    setPassword("");
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (phase === "submitting") return;
    const number = studentNumber.trim();
    const who = name.trim();
    if (!number || !password || (mode === "register" && !who)) return;

    setPhase("submitting");
    setError("");
    try {
      const data = mode === "register"
        ? await postJson("/api/student/register", {
            student_number: number, name: who, password,
          })
        : await postJson("/api/student/login", {
            student_number: number, password,
          });
      rememberStudent(data.student);
      onDone(data.student, data.courses || []);
    } catch (err) {
      setError(err && err.message ? err.message : "操作失败，请重试");
      setPhase("form");
    }
  }

  if (phase === "checking") {
    return <div className="login login--boot" aria-hidden="true" />;
  }

  const busy = phase === "submitting";
  const ready =
    studentNumber.trim() &&
    password &&
    (mode === "login" || name.trim()) &&
    !busy;

  return (
    <div className="login" role="dialog" aria-modal="true" aria-labelledby="login-title">
      <div className="login__backdrop" aria-hidden="true" />

      <form className="login__card" onSubmit={handleSubmit}>
        <span className="login__icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"
               strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 3 3 7.5l9 4.5 9-4.5L12 3Z" />
            <path d="M6 10v5.2c0 .9 2.7 2.8 6 2.8s6-1.9 6-2.8V10" />
            <path d="M21 7.5V13" />
          </svg>
        </span>

        <h1 className="login__title" id="login-title">
          {mode === "register" ? "注册学生账号" : "进入课堂"}
        </h1>
        <p className="login__subtitle">AI 学习空间 · 学生端</p>

        <div className="login__field">
          <label className="login__label" htmlFor="login-number">学号</label>
          <input
            id="login-number"
            ref={numberRef}
            className="login__input"
            value={studentNumber}
            onChange={(e) => { setStudentNumber(e.target.value); if (error) setError(""); }}
            placeholder="例如 2026001"
            autoComplete="username"
            disabled={busy}
          />
        </div>

        {mode === "register" ? (
          <div className="login__field">
            <label className="login__label" htmlFor="login-name">姓名</label>
            <input
              id="login-name"
              className="login__input"
              value={name}
              onChange={(e) => { setName(e.target.value); if (error) setError(""); }}
              placeholder="你的真实姓名"
              autoComplete="name"
              disabled={busy}
            />
          </div>
        ) : null}

        <div className="login__field">
          <label className="login__label" htmlFor="login-password">
            密码{mode === "register" ? "（至少 6 位）" : ""}
          </label>
          <input
            id="login-password"
            className="login__input"
            type="password"
            value={password}
            onChange={(e) => { setPassword(e.target.value); if (error) setError(""); }}
            placeholder={mode === "register" ? "设置一个密码" : "你的密码"}
            autoComplete={mode === "register" ? "new-password" : "current-password"}
            disabled={busy}
          />
        </div>

        {error ? <p className="login__error" role="alert">{error}</p> : null}

        <button type="submit" className="login__submit" disabled={!ready}>
          {busy ? "请稍候…" : mode === "register" ? "注册并进入" : "进入"}
          <span className="login__submit-arrow" aria-hidden="true">
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2"
                 strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 8h10M9 4l4 4-4 4" />
            </svg>
          </span>
        </button>

        <p className="login__switch">
          {mode === "register" ? "已经有账号？" : "还没有账号？"}
          <button
            type="button"
            className="login__switch-btn"
            onClick={() => switchMode(mode === "register" ? "login" : "register")}
            disabled={busy}
          >
            {mode === "register" ? "去登录" : "注册"}
          </button>
        </p>

        <p className="login__hint">课程码由任课老师提供，登录后即可加入课程。</p>
      </form>
    </div>
  );
}
