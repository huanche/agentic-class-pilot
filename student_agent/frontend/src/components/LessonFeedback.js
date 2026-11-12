export default function LessonFeedback({ feedback }) {
  if (!feedback) return <p className="done__sub">本次课堂已结束，暂无知识点反馈。</p>;
  if (feedback.typedTeaching) return <section className="lesson-feedback" aria-labelledby="lesson-feedback-title">
    <h4 id="lesson-feedback-title">本课学习反馈</h4>
    <p className="lesson-feedback__summary">{feedback.summary}</p>
    {[["mastered", "已掌握"], ["needs_review", "待巩固"], ["not_assessed", "尚未学习／评估"]].map(([category, label]) => {
      const points = feedback.points.filter(point => point.category === category);
      return points.length > 0 && <div key={category}><h5>{label}</h5>
        {points.map(point => <article key={point.id} className={`lesson-feedback__item lesson-feedback__item--${category}`}>
          <h5>{point.title} · {point.label}</h5>
          {point.knownParts?.length > 0 && <p><strong>你已经能：</strong>{point.knownParts.join("；")}</p>}
          {point.gaps?.length > 0 && <p><strong>还需巩固：</strong>{point.gaps.join("；")}</p>}
          {point.suggestion && <p><strong>下一步：</strong>{point.suggestion}</p>}
        </article>)}</div>;
    })}
  </section>;
  if (feedback.flowVersion === "dynamic_dialogue_v1") return <section className="lesson-feedback" aria-labelledby="lesson-feedback-title">
    <h4 id="lesson-feedback-title">本次交流记录</h4>
    <p className="lesson-feedback__summary">{feedback.summary}</p>
    <div className="lesson-feedback__list">{feedback.points.map(point => <article key={point.id} className="lesson-feedback__item">
      <h5>{point.title} · {point.label}</h5>
      {point.evidence && <p><strong>你的表达：</strong>{point.evidence}</p>}
      <p>{point.suggestion}</p>
    </article>)}</div>
    <p>其中 {feedback.assisted?.length || 0} 条表达前，本任务内已提供提示或讲解；未记录帮助不等于已证明独立掌握。</p>
    {!!feedback.unresolved?.length && <div><h5>仍需核对</h5><ul>{feedback.unresolved.map(item => <li key={item.observationId}>{item.questions}</li>)}</ul></div>}
    {!!feedback.contentLimitations?.length && <p>部分来源或图示未完整解析，相关判断仍有限制。</p>}
  </section>;
  return <section className="lesson-feedback" aria-labelledby="lesson-feedback-title">
    <h4 id="lesson-feedback-title">本节课知识点反馈</h4>
    <p className="lesson-feedback__summary">{feedback.summary}</p>
    <div className="lesson-feedback__list">
      {feedback.points.map((point, index) => <article
        className={`lesson-feedback__item lesson-feedback__item--${point.category}`} key={point.id}>
        <div className="lesson-feedback__heading">
          <h5>{index + 1}. {point.title}</h5>
          <span className="lesson-feedback__status">{point.label}</span>
        </div>
        <p className="lesson-feedback__rounds">首轮复述 {point.recallRounds} 次 · 加强复述 {point.reinforceRounds} 次{point.postclassRounds > 0 && ` · 课后补完 ${point.postclassRounds} 次`}</p>
        {point.evidence && <p className="lesson-feedback__evidence"><strong>判断依据：</strong>{point.evidence}</p>}
        {point.discussionNeedsReview && point.discussionEvidence && <p className="lesson-feedback__evidence"><strong>深入讨论：</strong>{point.discussionEvidence}</p>}
        {point.suggestion && !(point.category === "mastered" && point.suggestion === "可以用自己的话总结，并尝试举一个应用例子。") && <p>{point.suggestion}</p>}
        {point.excludedFromDiscussion && <p className="lesson-feedback__note">这个知识点仍需巩固，可在课后与 AI 继续复述。</p>}
      </article>)}
    </div>
  </section>;
}
