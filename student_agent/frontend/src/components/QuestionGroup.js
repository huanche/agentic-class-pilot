"use client";

import { useEffect, useState } from "react";

/** A group accepts partial answers; grading is always performed by the server. */
export default function QuestionGroup({ group, busy, onSubmit }) {
  const [answers, setAnswers] = useState({});
  const [questionIndex, setQuestionIndex] = useState(0);
  useEffect(() => { setAnswers({}); setQuestionIndex(0); }, [group?.id]);
  if (!group) return null;
  const results = group.results || {};
  const question = group.questions[questionIndex];
  const selected = question && !results[question.id] && answers[question.id] !== undefined
    ? { [question.id]: answers[question.id] } : {};
  return <section className="question-group" aria-label="知识点练习">
    <h4>知识点练习</h4>
    <p>第 {questionIndex + 1} / {group.questions.length} 题 · 可在下方输入框随时向 AI 提问。</p>
    {[question].map((question) => {
      const result = results[question.id];
      return <fieldset className="question-group__question" key={question.id} disabled={busy || Boolean(result)}>
        <legend>{questionIndex + 1}. {question.prompt}</legend>
        {question.options.map((option, choice) => <label className="question-group__option" key={choice}>
          <input type="radio" name={`question-${group.id}-${question.id}`} value={choice}
            checked={(result ? result.choice : answers[question.id]) === choice}
            onChange={() => setAnswers(current => ({ ...current, [question.id]: choice }))} />
          <span>{option}</span>
        </label>)}
        {result && <div className="question-group__feedback" role="status">
          <strong className={`question-group__result ${result.correct ? "question-group__result--correct" : "question-group__result--wrong"}`}>
            {result.correct ? "回答正确" : "回答错误"} <span>{result.correct ? "√" : "×"}</span>
          </strong>
          <p>你的答案：{question.options[result.choice]}</p>
          {!result.correct && <p>正确答案：{question.options[result.answer]}</p>}
          <p><strong>解析：</strong>{result.explanation}</p>
        </div>}
      </fieldset>;
    })}
    <div className="question-group__actions">
      {questionIndex > 0 && <button type="button" className="btn btn--ghost"
        disabled={busy} onClick={() => setQuestionIndex(index => index - 1)}>← 上一题</button>}
      {!results[question.id] && <button type="button" className="btn btn--primary"
        disabled={busy || !Object.keys(selected).length} onClick={() => onSubmit(group.id, selected)}>提交已完成的题目</button>}
      {results[question.id] && questionIndex < group.questions.length - 1 && <button type="button" className="btn btn--ghost"
        disabled={busy} onClick={() => setQuestionIndex(index => index + 1)}>下一题 →</button>}
    </div>
  </section>;
}
