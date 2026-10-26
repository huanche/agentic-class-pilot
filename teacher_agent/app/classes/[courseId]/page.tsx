'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
  ArrowLeft,
  BookOpen,
  Bot,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  FileText,
  Folder,
  Presentation,
  Sparkles,
  Users,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { CourseEnrollment } from '@/components/platform/course-enrollment';
import type { CourseModule, CourseStudentLearningState } from '@/lib/course-space/types';

type ClassResource = {
  id: string;
  title: string;
  origin: 'teacher' | 'agent';
  kind: 'material' | 'artifact';
  type?: string;
  status: string;
  url: string;
  activatedAt?: number;
  publicationId: string;
  publishedAt?: number;
  scope:
    | { type: 'course' }
    | { type: 'module'; moduleId: string }
    | { type: 'lesson'; lessonId: string }
    | { type: 'lessons'; lessonIds: string[] };
};

type Detail = {
  course: {
    id: string;
    title: string;
    subject?: string;
    gradeBand?: string;
    term?: string;
    description?: string;
    modules: CourseModule[];
  };
  resources: ClassResource[];
  students: CourseStudentLearningState[];
};

const statusLabel: Record<CourseStudentLearningState['status'], string> = {
  'not-started': '未开始',
  learning: '学习中',
  completed: '已完成',
  'needs-attention': '需要关注',
};

function PublishedResourceRow({ resource }: { resource: ClassResource }) {
  const Icon =
    resource.kind === 'material'
      ? FileText
      : resource.type === 'lesson-courseware'
        ? Presentation
        : Sparkles;
  return (
    <a
      href={resource.url}
      target="_blank"
      rel="noreferrer"
      className="group flex items-center gap-2 rounded-lg px-2 py-2 text-xs text-slate-600 hover:bg-[#B00055]/5 hover:text-[#8F0046]"
    >
      <Icon
        className={`size-4 shrink-0 ${resource.origin === 'teacher' ? 'text-blue-500' : 'text-fuchsia-500'}`}
      />
      <span className="min-w-0 flex-1 truncate">{resource.title}</span>
      <span
        className="shrink-0 rounded-full bg-emerald-50 px-2 py-0.5 font-mono text-[9px] text-emerald-700"
        title={resource.publicationId}
      >
        {resource.publicationId.slice(-6)}
      </span>
      <ExternalLink className="size-3.5 shrink-0 text-slate-300 group-hover:text-[#B00055]" />
    </a>
  );
}

export default function ClassDetailPage() {
  const { courseId } = useParams<{ courseId: string }>();
  const router = useRouter();
  const [detail, setDetail] = useState<Detail>();
  const [error, setError] = useState('');
  const [expandedModules, setExpandedModules] = useState<Set<string>>(new Set());
  const [expandedLessons, setExpandedLessons] = useState<Set<string>>(new Set());

  useEffect(() => {
    void fetch(`/api/classes/${courseId}`, { cache: 'no-store' })
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || '读取班级失败');
        setDetail(data);
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)));
  }, [courseId]);

  if (!detail) {
    return (
      <main className="grid min-h-screen place-items-center bg-slate-50 text-sm text-slate-500">
        {error || '正在读取班级…'}
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b bg-white px-6 py-4">
        <div className="mx-auto flex max-w-7xl items-center justify-between">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="icon" onClick={() => router.push('/classes')}>
              <ArrowLeft className="size-5" />
            </Button>
            <div>
              <h1 className="text-xl font-semibold">{detail.course.title}</h1>
              <p className="text-xs text-slate-500">
                {detail.course.subject || '课程'} · {detail.course.term || '当前学期'} · 授课中
              </p>
            </div>
          </div>
          <Button
            variant="outline"
            onClick={() => router.push(`/course-space?workspace=${detail.course.id}`)}
          >
            返回教师工作台
          </Button>
        </div>
      </header>

      <div className="mx-auto grid max-w-7xl gap-6 px-6 py-8 lg:grid-cols-[1.15fr_.85fr]">
        <section className="space-y-6">
          <CourseEnrollment courseId={courseId} />
          <div className="rounded-3xl bg-gradient-to-br from-[#B00055] to-[#78113f] p-7 text-white shadow-xl">
            <p className="text-xs font-medium tracking-widest text-white/60">CLASS OVERVIEW</p>
            <h2 className="mt-3 text-3xl font-semibold">{detail.course.title}</h2>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-white/75">
              {detail.course.description || '本区域汇集教师已经面向班级激活的课程资料与教学产物。'}
            </p>
            <div className="mt-6 flex gap-3 text-xs">
              <span className="rounded-full bg-white/12 px-3 py-1.5">
                {detail.course.modules.length} 个模块
              </span>
              <span className="rounded-full bg-white/12 px-3 py-1.5">
                {detail.resources.length} 项已发布资料
              </span>
            </div>
          </div>

          <div className="rounded-3xl border bg-white p-6 shadow-sm">
            <div className="flex items-center gap-2">
              <BookOpen className="size-5 text-[#B00055]" />
              <h2 className="text-lg font-semibold">已公布课程资料</h2>
            </div>
            <p className="mt-1 text-xs text-slate-500">
              仅显示教师逐项确认发布的材料和 AI 产物；发布后不可撤回。
            </p>
            <div className="mt-5 overflow-hidden rounded-2xl border bg-slate-50/60">
              <div className="border-b bg-white px-4 py-3">
                <div className="flex items-center gap-2 text-sm font-semibold">
                  <Folder className="size-4 text-[#B00055]" />
                  课程级文件
                  <span className="ml-auto text-xs font-normal text-slate-400">
                    {detail.resources.filter((item) => item.scope.type === 'course').length} 项
                  </span>
                </div>
                <div className="ml-6 mt-1 border-l pl-2">
                  {detail.resources.filter((item) => item.scope.type === 'course').length ? (
                    detail.resources
                      .filter((item) => item.scope.type === 'course')
                      .map((resource) => (
                        <PublishedResourceRow key={resource.id} resource={resource} />
                      ))
                  ) : (
                    <p className="px-2 py-2 text-xs text-slate-400">等待教师发布课程级产物</p>
                  )}
                </div>
              </div>
              <div className="max-h-[620px] overflow-y-auto p-3">
                {detail.course.modules.map((module) => {
                  const moduleResources = detail.resources.filter(
                    (item) => item.scope.type === 'module' && item.scope.moduleId === module.id,
                  );
                  const moduleOpen = expandedModules.has(module.id);
                  const lessonResourceCount = module.lessons.reduce(
                    (count, lesson) =>
                      count +
                      detail.resources.filter(
                        (item) =>
                          (item.scope.type === 'lesson' && item.scope.lessonId === lesson.id) ||
                          (item.scope.type === 'lessons' &&
                            item.scope.lessonIds.includes(lesson.id)),
                      ).length,
                    0,
                  );
                  return (
                    <div key={module.id} className="mb-1">
                      <button
                        type="button"
                        onClick={() =>
                          setExpandedModules((current) => {
                            const next = new Set(current);
                            if (next.has(module.id)) next.delete(module.id);
                            else next.add(module.id);
                            return next;
                          })
                        }
                        className="flex w-full items-center gap-2 rounded-xl px-2 py-2 text-left text-sm hover:bg-white"
                      >
                        {moduleOpen ? (
                          <ChevronDown className="size-4 text-slate-400" />
                        ) : (
                          <ChevronRight className="size-4 text-slate-400" />
                        )}
                        <Folder className="size-4 text-amber-500" />
                        <span className="min-w-0 flex-1 truncate font-medium">{module.title}</span>
                        <span className="text-xs text-slate-400">
                          {moduleResources.length + lessonResourceCount} 项
                        </span>
                      </button>
                      {moduleOpen && (
                        <div className="ml-5 border-l pl-2">
                          {moduleResources.map((resource) => (
                            <PublishedResourceRow key={resource.id} resource={resource} />
                          ))}
                          {module.lessons.map((lesson) => {
                            const lessonResources = detail.resources.filter(
                              (item) =>
                                (item.scope.type === 'lesson' &&
                                  item.scope.lessonId === lesson.id) ||
                                (item.scope.type === 'lessons' &&
                                  item.scope.lessonIds.includes(lesson.id)),
                            );
                            const lessonOpen = expandedLessons.has(lesson.id);
                            return (
                              <div key={lesson.id}>
                                <button
                                  type="button"
                                  onClick={() =>
                                    setExpandedLessons((current) => {
                                      const next = new Set(current);
                                      if (next.has(lesson.id)) next.delete(lesson.id);
                                      else next.add(lesson.id);
                                      return next;
                                    })
                                  }
                                  className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-xs hover:bg-white"
                                >
                                  {lessonOpen ? (
                                    <ChevronDown className="size-3.5 text-slate-400" />
                                  ) : (
                                    <ChevronRight className="size-3.5 text-slate-400" />
                                  )}
                                  <Folder className="size-3.5 text-[#B00055]" />
                                  <span className="min-w-0 flex-1 truncate">{lesson.title}</span>
                                  <span className="text-[10px] text-slate-400">
                                    {lessonResources.length}
                                  </span>
                                </button>
                                {lessonOpen && (
                                  <div className="ml-5 border-l pl-2">
                                    {lessonResources.length ? (
                                      lessonResources.map((resource) => (
                                        <PublishedResourceRow
                                          key={`${lesson.id}-${resource.id}`}
                                          resource={resource}
                                        />
                                      ))
                                    ) : (
                                      <p className="px-2 py-2 text-[11px] text-slate-400">
                                        等待教师发布产物
                                      </p>
                                    )}
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </section>

        <section className="rounded-3xl border bg-white p-6 shadow-sm">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Users className="size-5 text-[#B00055]" />
              <h2 className="text-lg font-semibold">学生与学习状态</h2>
            </div>
            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-500">
              {detail.students.length} 人
            </span>
          </div>
          {detail.students.length === 0 ? (
            <div className="mt-6 rounded-2xl border border-dashed p-10 text-center">
              <Bot className="mx-auto size-10 text-slate-300" />
              <h3 className="mt-3 font-medium">尚未同步学生名单</h3>
              <p className="mt-2 text-xs leading-5 text-slate-400">
                接入底座的班级与学生账号后，姓名、学习进度和最近活动会显示在这里。
              </p>
            </div>
          ) : (
            <div className="mt-5 space-y-3">
              {detail.students.map((student) => (
                <div key={student.studentId} className="rounded-2xl border p-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="font-medium">{student.name}</p>
                      <p className="text-[11px] text-slate-400">
                        {student.studentNumber || student.studentId} ·{' '}
                        {student.className || '当前班级'}
                      </p>
                    </div>
                    <span
                      className={`rounded-full px-2.5 py-1 text-[11px] ${student.status === 'needs-attention' ? 'bg-red-50 text-red-600' : student.status === 'completed' ? 'bg-emerald-50 text-emerald-700' : 'bg-blue-50 text-blue-700'}`}
                    >
                      {statusLabel[student.status]}
                    </span>
                  </div>
                  <div className="mt-4 flex items-center gap-3">
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
                      <div
                        className="h-full rounded-full bg-[#B00055]"
                        style={{ width: `${Math.min(100, Math.max(0, student.progress))}%` }}
                      />
                    </div>
                    <span className="text-xs font-medium tabular-nums">{student.progress}%</span>
                  </div>
                  <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-500">
                    {typeof student.totalLessons === 'number' && student.totalLessons > 0 && (
                      <span>已学 {student.learnedLessons ?? 0}/{student.totalLessons} 节</span>
                    )}
                    {typeof student.sessionCount === 'number' && student.sessionCount > 0 && (
                      <span>会话 {student.sessionCount} 次 · 完成 {student.endedCount ?? 0}</span>
                    )}
                    {!!student.stars && <span className="text-amber-500">知识点 ★ {student.stars}</span>}
                    {!!student.lastActiveAt && (
                      <span>
                        最近活跃 {new Date(student.lastActiveAt).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
