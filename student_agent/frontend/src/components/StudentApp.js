"use client";

import { useEffect, useState } from "react";
import { legacyMarkup } from "./legacyMarkup";
import { courseMarkup } from "./courseMarkup";
import { registerVideoPlayer } from "../legacy/video-player.js";
import { platformPlayerAdapter } from "../integration/platform-player-adapter.js";

registerVideoPlayer(platformPlayerAdapter);

const appMarkup = legacyMarkup
  .replace('<main class="app">', '<main class="app">' + courseMarkup)
  .replace('<section class="hub" id="hub"', '<section class="hub" id="hub" hidden');

export default function StudentApp() {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let active = true;
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
    }

    // Resolve and pin the platform course before the legacy router reads its
    // catalog. Otherwise it may cache the session id from a previously opened
    // course and briefly render that course's lessons.
    const prepareCourse = token
      ? import("../legacy/api.js").then((api) =>
          api.startSession({ timeScale: 1 }).then((result) => {
            try { sessionStorage.setItem("__studentSessionId", result.session_id); } catch (e) {}
            return api.fetchStudentCourses(result.session_id);
          }).then((courses) => {
            const course = courses && courses[0];
            if (course && window.location.hash === "") {
              window.location.hash = `/course/${encodeURIComponent(course.courseId)}`;
            }
          })
        ).catch((error) => {
          console.error("平台课程初始化失败", error);
        })
      : Promise.resolve();

    prepareCourse.then(() => import("../legacy/app.js")).then(() => {
      if (!active) return;
      setReady(true);
    }).catch((error) => {
      console.error("学生端初始化失败", error);
    });

    return () => {
      active = false;
    };
  }, []);

  return (
    <div
      data-app-ready={ready ? "true" : "false"}
      dangerouslySetInnerHTML={{ __html: appMarkup }}
    />
  );
}
