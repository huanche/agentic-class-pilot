/* Demo course data — ONLY loaded when the backend runs in demo mode
   (STUDENT_DEMO_MODE=true). Production sessions always resolve courses from
   the platform learning context; this module is never a fallback. */
export var LESSON = {
  lessonId: LESSON_ID,
  course: "操作系统",
  chapter: "第 3 周",
  title: "处理机调度",
  summary: "CPU 一次只能服务一个进程，系统需要决定多个就绪进程先服务谁。",
  estimatedMinutes: 45,
  knowledgePointCount: 6,
  segmentCount: 6,
  knowledgePoints: [
    "调度是什么", "三级调度", "调度评价指标",
    "FCFS 与 SJF", "抢占式与非抢占式", "时间片轮转与多级反馈队列"
  ],
  /* 起止秒数是整条视频上的时间段，对应 lesson-data/segments/*.json 的
     source.position（后端那边目前也是占位值，等视频接入再对齐） */
  segments: [
    { segmentId: "seg-001", title: "调度是什么、为什么需要调度",   order: 1, startSeconds: 750,  endSeconds: 1080 },
    { segmentId: "seg-002", title: "三级调度：高级、中级、低级",   order: 2, startSeconds: 1080, endSeconds: 1410 },
    { segmentId: "seg-003", title: "调度评价指标",                 order: 3, startSeconds: 1410, endSeconds: 1740 },
    { segmentId: "seg-004", title: "FCFS 与 SJF",                 order: 4, startSeconds: 1740, endSeconds: 2070 },
    { segmentId: "seg-005", title: "抢占式与非抢占式",             order: 5, startSeconds: 2070, endSeconds: 2400 },
    { segmentId: "seg-006", title: "时间片轮转与多级反馈队列",     order: 6, startSeconds: 2400, endSeconds: 2700 }
  ]
};

/* 后端目前只配了这一节课（lesson-data/lesson-plan.json），
   所以目录里就只有它。真实选课应由后端下发，届时把这个函数换成请求即可。 */
export function fetchStudentCourses() {
  return Promise.resolve([{
    courseId: "operating-systems",
    name: "操作系统",
    summary: "从进程与资源管理出发，理解计算机如何协调多个任务。",
    icon: "⌘",
    currentWeek: 3,
    lessons: [{
      lessonId: LESSON_ID,
      week: 3,
      chapter: "第 3 周",
      title: LESSON.title,
      summary: LESSON.summary,
      /* 后端允许随时开课（/start 幂等，已结束的会话也能恢复），
         所以不按日历推断「已上过 / 未上过」，一律可进。 */
      status: "current",
      estimatedMinutes: LESSON.estimatedMinutes,
      knowledgePoints: LESSON.knowledgePoints
    }]
  }]);
}

export function fetchLesson(lessonId) {
  if (lessonId && lessonId !== LESSON_ID) {
    return Promise.reject(new Error("这节课尚未开放：" + lessonId));
  }
  return Promise.resolve(LESSON);
}
