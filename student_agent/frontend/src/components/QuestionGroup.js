"use client";

import { useEffect, useState } from "react";

/** A group accepts partial answers; grading is always performed by the server. */
export default function QuestionGroup({ group, busy, onSubmit }) {
  const [answers, setAnswers] = useState({});
  useEffect(() => { setAnswers({}); }, [group?.id]);
  if (!group) return null;
  const results = group.results || {};
  const selected = Object.fromEntries(Object.entries(answers).filter(([id]) => !results[id]));
  return <section className="question-group" aria-label="知识点练习">
    <h4>知识点练习</h4>
    <p>可以先提交已完成的题目，其他题目会保留。</p>
    {group.questions.map((question, index) => {
      const result = results[question.id];
      return <fieldset className="question-group__question" key={question.id} disabled={busy || Boolean(result)}>
        <legend>{index + 1}. {question.prompt}</legend>
        {question.options.map((option, choice) => <label className="question-group__option" key={choice}>
          <input type="radio" name={`question-${group.id}-${question.id}`} value={choice}
            checked={(result ? result.choice : answers[question.id]) === choice}
            onChange={() => setAnswers(current => ({ ...current, [question.id]: choice }))} />
          <span>{option}</span>
        </label>)}
        {result && <p role="status">{result.correct ? "回答正确" : `再看看，正确答案：${question.options[result.answer]}`}<br />{result.explanation}</p>}
      </fieldset>;
    })}
    {group.questions.some(question => !results[question.id]) && <button type="button" className="btn btn--primary"
      disabled={busy || !Object.keys(selected).length} onClick={() => onSubmit(group.id, selected)}>提交已完成的题目</button>}
  </section>;
}
