const STEPS = [
  { id: "video", title: "教学视频", detail: "观看本课内容" },
  { id: "recall", title: "初始复述", detail: "逐个回顾知识点" },
  { id: "reinforce", title: "加强复述", detail: "补强未掌握的内容" },
  { id: "discuss", title: "深入讨论", detail: "应用与思考" },
  { id: "wrapup", title: "课堂总结", detail: "查看个人学习反馈" },
];

export const STAGE_TITLES = Object.fromEntries(STEPS.map(({ id, title }) => [id, title]));

export default function LessonProgress({ phase, agentStage, progress, postclassStage }) {
  const finished = ["done", "replay", "postclass"].includes(phase);
  const current = phase === "video" ? 0 : Math.max(1, STEPS.findIndex((step) => step.id === agentStage));
  return <aside className="lesson-progress" aria-label="课堂阶段进度">
    <p className="lesson-progress__eyebrow">本课学习进度</p>
    <ol className="lesson-progress__steps">
      {STEPS.map((step, index) => {
        const past = index < current || (finished && (index === current || step.id === "wrapup"));
        const active = !finished && index === current;
        const skipped = past && ((step.id === "reinforce" && !progress?.reinforcementStarted)
          || (step.id === "discuss" && !progress?.discussionTurns));
        const endedEarly = finished && current < 4 && index === current;
        const status = active ? "进行中" : endedEarly ? "已提前结束" : skipped ? "无需开展" : past ? "已完成" : finished ? "未开展" : "待开始";
        return <li key={step.id} className={`lesson-progress__step${active ? " is-current" : ""}${past ? " is-past" : ""}`}
          aria-current={active ? "step" : undefined}>
          <span className="lesson-progress__marker" aria-hidden="true">{past ? skipped || endedEarly ? "–" : "✓" : index + 1}</span>
          <div><strong>{step.title}</strong><span className="lesson-progress__status">{status}</span>
            <p>{active && step.id === "recall" && progress
              ? `已回顾 ${progress.recallCompleted} / ${progress.total} 个知识点`
              : active && step.id === "discuss" && progress
                ? `已讨论 ${progress.discussionTurns} / ${progress.discussionLimit} 个知识点`
                : step.detail}</p></div>
        </li>;
      })}
    </ol>
    <p className="lesson-progress__note">{phase === "postclass"
      ? postclassStage === "open" ? "课后内容已补完，现在可自由提问。" : "课堂已结束，正在课后补完。"
      : finished ? "课堂已结束，可以回看视频或继续课后对话。"
        : agentStage === "wrapup" ? "课堂对话已完成，请查看学习反馈。"
          : "按当前阶段学习，AI 会提示下一阶段。"}</p>
  </aside>;
}
