"use client";

import { useCallback, useEffect, useState } from "react";
import { legacyMarkup } from "./legacyMarkup";
import { courseMarkup } from "./courseMarkup";
import StudentLogin from "./StudentLogin";
import StudentEnroll from "./StudentEnroll";
import { registerVideoPlayer } from "../legacy/video-player.js";
import { platformPlayerAdapter } from "../integration/platform-player-adapter.js";

const appMarkup = legacyMarkup
  .replace('<main class="app">', '<main class="app">' + courseMarkup)
  .replace('<section class="hub" id="hub"', '<section class="hub" id="hub" hidden');

export default function StudentApp() {
  // boot  = 还没判定入口方式（避免登录页闪一下）
  // auth  = 独立入口：登录/注册（含会话检查）；enroll = 一门课都没有，先加入；
  // app   = 正常上课
  const [gate, setGate] = useState("boot");
  // 已经在应用里，又点开"加入课程"（和上面的 enroll 门是两回事）
  const [enrolling, setEnrolling] = useState(false);
  const [ready, setReady] = useState(false);
  // 平台深链入口（URL 带 launch_token）：跳过登录门，身份以令牌为准
  const [platformEntry, setPlatformEntry] = useState(false);

  const handleAuth = useCallback((student, courses) => {
    setGate(Array.isArray(courses) && courses.length ? "app" : "enroll");
  }, []);

  // 入口判定。平台深链跳过登录门；独立入口走上游的登录/选课流程。
  // 读 window 必须在 effect 里：output:"export" 会在构建期预渲染本组件。
  useEffect(() => {
    const url = new URL(window.location.href);
    const token = url.searchParams.get("launch_token");
    if (token) {
      // Keep the short-lived token out of copied URLs and browser history.
      // Use TWO mechanisms: a window global AND a sessionStorage bridge that
      // the legacy api.js reads synchronously (dynamic-import chunk timing).
      window.__studentLaunchToken = token;
      try { sessionStorage.setItem("__launch_token", token); } catch (e) {}
      url.searchParams.delete("launch_token");
      window.history.replaceState({}, "", url);
      setPlatformEntry(true);
      setGate("app");
      return;
    }
    // 刷新 / 回退时 token 已从 URL 摘掉 —— sessionStorage 里还有就仍是平台态，
    // 直接回课堂，不要落到独立登录页（平台部署下那页只会误导）。
    let stored = "";
    try { stored = sessionStorage.getItem("__launch_token") || ""; } catch (e) {}
    if (stored) {
      window.__studentLaunchToken = stored;
      setPlatformEntry(true);
      setGate("app");
      return;
    }
    // 平台部署下直接访问 /app（无令牌、无会话）→ 回平台首页，
    // 不再展示独立的登录 / 加入课程页。独立态只保留给本机开发。
    const host = window.location.hostname;
    if (host !== "localhost" && host !== "127.0.0.1") {
      window.location.replace("/");
      return;
    }
    setGate("auth");
  }, []);

  // 登录通过（或平台深链）之后才加载 legacy 应用 —— 别让它在登录页背后偷偷发请求
  useEffect(() => {
    if (gate !== "app") return;
    let active = true;

    const bootLegacy = () => {
      import("../legacy/app.js").then(() => {
        if (active) setReady(true);
      }).catch((error) => {
        console.error("学生端初始化失败", error);
      });
    };

    if (platformEntry) {
      // 平台播放器适配层：把课堂视频区换成教师端播放器 iframe。
      // 只在平台入口注册 —— 独立态没有 platform lesson，适配器 mount 会抛错。
      registerVideoPlayer(platformPlayerAdapter);
      import("../platform/playerAdapter.js").catch(function (error) {
        console.error("播放器适配层加载失败", error);
      });
      // 平台深链：**先**建立会话并把 hash 指到对应课程的课时列表，**再**加载
      // legacy 应用 —— 它启动即按当前 hash 渲染，空 hash 会先闪一下
      // 「我的课程」页（/app#）再跳到选择课时。会话先行也保证课程接口能带上
      // sessionId（learning_context 靠它定位）。
      import("../legacy/api.js").then((api) => {
        return api.startSession({ timeScale: 1 }).then((result) => {
          try { sessionStorage.setItem("__studentSessionId", result.sessionId); } catch (e) {}
          if (window.location.hash !== "") return; // 用户带着具体课时链接进来，别覆盖
          // 平台链路用会话的 learning_context 取课程，不用本系统的学生账号接口
          return api.fetchSessionCourses(result.sessionId).then((courses) => {
            const course = courses && courses[0];
            if (course) {
              window.location.hash = `/course/${encodeURIComponent(course.courseId)}`;
            }
          });
        });
      }).then(bootLegacy).catch((error) => {
        console.error("平台课程初始化失败", error);
        bootLegacy(); // 会话建立失败也别白屏 —— 退回 legacy 自身的错误提示
      });
    } else {
      bootLegacy();
    }

    return () => {
      active = false;
    };
  }, [gate, platformEntry]);

  const handleJoined = useCallback(() => {
    if (enrolling) {
      // 应用已经在跑，课程列表是它启动时拉的 —— 重载一次最省事也最可靠
      window.location.reload();
    } else {
      setGate("app");
    }
  }, [enrolling]);

  // 判定完成前不渲染，避免独立入口闪一下登录页
  if (gate === "boot") return null;

  if (gate === "auth") {
    return <StudentLogin onDone={handleAuth} />;
  }

  if (gate === "enroll") {
    // required：一门课都没有，没有"稍后再说"这个退路
    return <StudentEnroll required onDone={handleJoined} />;
  }

  return (
    <>
      <div
        data-app-ready={ready ? "true" : "false"}
        dangerouslySetInnerHTML={{ __html: appMarkup }}
      />

      {/* 平台态不显示「加入课程」：选课由平台侧管理，这里点进去会打到本系统
          自建的 /api/student/join（平台学生没有那个账号），必然失败。 */}
      {ready && !platformEntry ? (
        <button
          type="button"
          className="join-fab"
          onClick={() => setEnrolling(true)}
        >
          加入课程
        </button>
      ) : null}

      {enrolling ? (
        <StudentEnroll
          onDone={handleJoined}
          onSkip={() => setEnrolling(false)}
        />
      ) : null}
    </>
  );
}
