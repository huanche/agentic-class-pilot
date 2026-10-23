export default function LessonFeedback({ feedback }) {
  if (!feedback) return <p className="done__sub">本次课堂已结束，暂无知识点反馈。</p>;
  return <section className="lesson-feedback" aria-labelledby="lesson-feedback-title">
    <h4 id="lesson-feedback-title">本节课知识点反馈</h4>
    <p className="lesson-feedback__summary">{feedback.summary}</p>
    {feedback.preparationCoverage?.partial && <p role="status">本次仅整理出 {feedback.preparationCoverage.acceptedCount} 个可核对原文的知识点，反馈范围可能不完整。</p>}
    <div className="lesson-feedback__list">
      {feedback.points.map((point, index) => <article
        className={`lesson-feedback__item lesson-feedback__item--${point.category}`} key={point.id}>
        <div className="lesson-feedback__heading">
          <h5>{index + 1}. {point.title}</h5>
          <span className="lesson-feedback__status">{point.label}</span>
        </div>
        <p className="lesson-feedback__rounds">首轮复述 {point.recallRounds} 次 · 加强复述 {point.reinforceRounds} 次{point.postclassRounds > 0 && ` · 课后补完 ${point.postclassRounds} 次`}</p>
        {point.evidence && <p className="lesson-feedback__evidence"><strong>判断依据：</strong>{point.evidence}</p>}
        {point.suggestion && !(point.category === "mastered" && point.suggestion === "可以用自己的话总结，并尝试举一个应用例子。") && <p>{point.suggestion}</p>}
        {point.excludedFromDiscussion && <p className="lesson-feedback__note">这个知识点仍需巩固，可在课后与 AI 继续复述。</p>}
      </article>)}
    </div>
  </section>;
}
