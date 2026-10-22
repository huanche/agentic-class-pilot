"use client";

import { useEffect, useState } from "react";
import { legacyMarkup } from "./legacyMarkup";
import { courseMarkup } from "./courseMarkup";
import { registerVideoPlayer } from "../legacy/video-player.js";
import { platformPlayerAdapter } from "../integration/platform-player-adapter.js";

const appMarkup = legacyMarkup
  .replace('<main class="app">', '<main class="app">' + courseMarkup)
  .replace('<section class="hub" id="hub"', '<section class="hub" id="hub" hidden');

export default function StudentApp() {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const url = new URL(window.location.href);
    const token = url.searchParams.get("launch_token");
    if (token) {
      window.__studentLaunchToken = token;
      try { sessionStorage.setItem("__launch_token", token); } catch (error) {}
      url.searchParams.delete("launch_token");
      window.history.replaceState({}, "", url);
    }

    let stored = "";
    try { stored = sessionStorage.getItem("__launch_token") || ""; } catch (error) {}
    const launchToken = token || stored;
    if (!launchToken) {
      window.location.replace("/");
      return;
    }

    window.__studentLaunchToken = launchToken;
    let active = true;
    registerVideoPlayer(platformPlayerAdapter);

    import("../legacy/api.js").then((api) => api.startSession({ timeScale: 1 }))
      .then((result) => {
        try { sessionStorage.setItem("__studentSessionId", result.sessionId); } catch (error) {}
        if (window.location.hash) return;
        return import("../legacy/api.js").then((api) =>
          api.fetchSessionCourses(result.sessionId).then((courses) => {
            const course = courses && courses[0];
            if (course) window.location.hash = `/course/${encodeURIComponent(course.courseId)}`;
          })
        );
      })
      .then(() => import("../legacy/app.js"))
      .then(() => { if (active) setReady(true); })
      .catch((error) => {
        console.error("平台课堂初始化失败", error);
        window.location.replace("/");
      });

    return () => { active = false; };
  }, []);

  return (
    <div
      data-app-ready={ready ? "true" : "false"}
      dangerouslySetInnerHTML={{ __html: appMarkup }}
    />
  );
}
