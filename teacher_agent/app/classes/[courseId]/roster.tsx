'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';

type Lesson = { id: string; title: string; classroomId: string; total: number | null };
type Student = {
  studentId: string; name: string; online: boolean; classroomIds: string[];
  mastered: Record<string, number>; grade?: string; studentNumber?: string; major?: string;
};
type Assessment = { lessonId: string; pointId: string; title: string; status: string; stars: number; evidence?: string };
type Roster = { lessons: Lesson[]; students: Student[]; assessments: Assessment[] };

function useRoster(courseId: string, studentId?: string) {
  const [data, setData] = useState<Roster>();
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    const query = studentId ? `?student=${encodeURIComponent(studentId)}` : '';
    let pending = false;
    const refresh = async () => {
      if (pending || document.hidden) return;
      pending = true;
      try {
        const response = await fetch(`/api/classes/${encodeURIComponent(courseId)}/roster${query}`,
          { signal: controller.signal, cache: 'no-store' });
        const body = await response.json();
        if (!response.ok) throw new Error(body.error || '读取学生学情失败');
        if (!controller.signal.aborted) { setData(body); setError(''); }
      } catch (reason) {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '读取学生学情失败');
      } finally {
        pending = false;
      }
    };
    setData(undefined);
    setError('');
    void refresh();
    const timer = window.setInterval(refresh, 20000);
    document.addEventListener('visibilitychange', refresh);
    return () => {
      controller.abort();
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', refresh);
    };
  }, [courseId, studentId]);
  return { data, error };
}

function progress(student: Student, lessons: Lesson[]) {
  const total = lessons.reduce((sum, lesson) => sum + (lesson.total ?? 0), 0);
  if (!total || lessons.some(lesson => lesson.total === null)) return '待统计';
  const mastered = lessons.reduce((sum, lesson) => sum + (student.mastered[lesson.id] ?? 0), 0);
  return `${mastered}/${total}（${Math.round(mastered / total * 100)}%）`;
}

function activity(student: Student, lesson?: Lesson) {
  if (!student.online) return { label: '不活跃', color: 'bg-white' };
  if (lesson && student.classroomIds.includes(lesson.classroomId)) {
    return { label: '正在学习', color: 'border-red-200 bg-red-50' };
  }
  return { label: '在线', color: 'border-blue-200 bg-blue-50' };
}

export function StudentRoster({ courseId }: { courseId: string }) {
  const { data, error } = useRoster(courseId);
  const [selectedId, setSelectedId] = useState('');
  const lesson = data?.lessons.find(item => item.id === selectedId) ?? data?.lessons[0];
  return (
    <section className="self-start rounded-3xl border bg-white p-5 shadow-sm">
      <h2 className="text-lg font-semibold">学生与学习状态 {data && <small className="text-slate-500">{data.students.length} 人</small>}</h2>
      {error ? <p role="alert" className="mt-3 text-sm text-red-700">{error}</p> :
        !data ? <p className="mt-3 text-sm text-slate-500">正在读取学生学情…</p> : (
          <>
            <label className="mt-3 flex items-center gap-2 text-sm">
              <span className="shrink-0">观察课件</span>
              <select className="min-w-0 flex-1 rounded-md border p-2" value={lesson?.id ?? ''}
                onChange={event => setSelectedId(event.target.value)} disabled={!data.lessons.length}>
                {!data.lessons.length && <option value="">暂无已发布课件</option>}
                {data.lessons.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}
              </select>
            </label>
            {!data.students.length && <p className="mt-4 text-sm text-slate-500">尚无学生加入课程</p>}
            <ul className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
              {data.students.map(student => {
                const state = activity(student, lesson);
                const query = lesson ? `?lesson=${encodeURIComponent(lesson.id)}` : '';
                return <li key={student.studentId} className="min-w-0">
                  <Link href={`/classes/${encodeURIComponent(courseId)}/students/${encodeURIComponent(student.studentId)}${query}`}
                    className={`block h-full rounded-md border p-2 text-xs hover:border-slate-500 focus-visible:outline-2 ${state.color}`}>
                    <span className="block break-all font-semibold">{student.name}</span>
                    <span className="mt-1 block text-slate-600">全课 {progress(student, data.lessons)}</span>
                    <span className="block text-slate-600">本课 {progress(student, lesson ? [lesson] : [])}</span>
                    <span className="mt-1 block">{state.label}</span>
                  </Link>
                </li>;
              })}
            </ul>
          </>
        )}
    </section>
  );
}

export function StudentLearningDetail({ courseId, studentId, lessonId }: {
  courseId: string; studentId: string; lessonId?: string;
}) {
  const { data, error } = useRoster(courseId, studentId);
  const student = data?.students[0];
  const lesson = data?.lessons.find(item => item.id === lessonId) ?? data?.lessons[0];
  return <main className="mx-auto max-w-4xl space-y-5 p-6">
    <Link href={`/classes/${encodeURIComponent(courseId)}`} className="text-sm underline">返回授课管理</Link>
    {error ? <p role="alert">{error}</p> : !data || !student ? <p>正在读取学生详情…</p> : <>
      <h1 className="text-xl font-semibold">{student.name}的学习详情</h1>
      <dl className="grid grid-cols-2 gap-3 rounded-xl border p-4 text-sm">
        {[['年级', student.grade], ['学号', student.studentNumber], ['专业', student.major]].map(([label, value]) =>
          <div key={label}><dt>{label}</dt><dd>{value || '未录入'}</dd></div>)}
        <div><dt>整门课知识点掌握</dt><dd>{progress(student, data.lessons)}</dd></div>
        <div><dt>{lesson?.title ?? '当前课件'}知识点掌握</dt><dd>{progress(student, lesson ? [lesson] : [])}</dd></div>
        <div><dt>当前活动状态</dt><dd>{activity(student, lesson).label}</dd></div>
      </dl>
      <h2 className="text-lg font-semibold">知识点评估</h2>
      {data.assessments.length === 0 && <p className="text-sm text-slate-500">暂无当前发布版本的评估记录</p>}
      {data.lessons.map(item => {
        const rows = data.assessments.filter(row => row.lessonId === item.id);
        return <section key={item.id} className="space-y-2 rounded-xl border p-4">
          <h3 className="font-medium">{item.title}{item.id === lesson?.id ? '（所选课件）' : ''}</h3>
          <p className="text-sm">掌握 {progress(student, [item])}</p>
          {rows.map(row => <div className="text-sm" key={row.pointId}>
            <p>{row.title} · {row.status} · {row.stars} 星</p>
            {row.evidence && <p className="text-slate-500">{row.evidence}</p>}
          </div>)}
        </section>;
      })}
    </>}
  </main>;
}
