'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowLeft, BookOpenCheck, ChevronRight, GraduationCap, Users } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { platformHomeUrl } from '@/lib/integration/platform-links';

type ClassCourse = {
  id: string;
  title: string;
  subject?: string;
  gradeBand?: string;
  term?: string;
  description?: string;
  moduleCount: number;
  lessonCount: number;
  studentCount: number;
  updatedAt: number;
};

export default function ClassesPage() {
  const router = useRouter();
  const [courses, setCourses] = useState<ClassCourse[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void fetch('/api/classes', { cache: 'no-store' })
      .then((response) => response.json())
      .then((data) => setCourses(data.courses ?? []))
      .finally(() => setLoading(false));
  }, []);

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_20%_5%,rgba(176,0,85,.1),transparent_30%),#f8fafc] text-slate-900">
      <header className="border-b border-white/70 bg-white/80 px-6 py-4 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="icon" aria-label="返回管理平台" onClick={() => window.location.assign(platformHomeUrl())}>
              <ArrowLeft className="size-5" />
            </Button>
            <img src="/mentra-logo.svg" alt="MENTRA" className="h-9 w-auto" />
            <div>
              <h1 className="text-xl font-semibold">授课 Class</h1>
              <p className="text-xs text-slate-500">显示课程通道已经发布的课程</p>
            </div>
          </div>
          <Button variant="outline" onClick={() => router.push('/course-space')}>
            进入课程通道
          </Button>
        </div>
      </header>

      <section className="mx-auto max-w-7xl px-6 py-10">
        <div className="mb-7">
          <p className="text-sm font-medium text-[#B00055]">CURRENT CLASSES</p>
          <h2 className="mt-2 text-3xl font-semibold">教师当前正在授课的课程</h2>
          <p className="mt-2 text-sm text-slate-500">
            发布课程后自动进入这里；课程资料仍由教师逐项激活。
          </p>
        </div>

        {loading ? (
          <div className="rounded-3xl border bg-white p-12 text-center text-sm text-slate-400">
            正在读取班级课程…
          </div>
        ) : courses.length === 0 ? (
          <div className="rounded-3xl border border-dashed bg-white/80 p-14 text-center">
            <BookOpenCheck className="mx-auto size-12 text-slate-300" />
            <h3 className="mt-4 text-lg font-semibold">还没有正在授课的课程</h3>
            <p className="mt-2 text-sm text-slate-500">请先在课程通道完成审核并发布课程。</p>
            <Button
              className="mt-6 bg-[#B00055] hover:bg-[#8F0046]"
              onClick={() => router.push('/course-space')}
            >
              前往课程通道
            </Button>
          </div>
        ) : (
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
            {courses.map((course) => (
              <button
                key={course.id}
                onClick={() => router.push(`/classes/${course.id}`)}
                className="group overflow-hidden rounded-3xl border border-white bg-white text-left shadow-[0_18px_55px_-38px_rgba(15,23,42,.55)] transition hover:-translate-y-1 hover:border-[#B00055]/25 hover:shadow-[0_24px_65px_-38px_rgba(176,0,85,.38)]"
              >
                <div className="h-2 bg-gradient-to-r from-[#B00055] via-pink-400 to-blue-400" />
                <div className="p-6">
                  <div className="flex items-start justify-between">
                    <span className="grid size-11 place-items-center rounded-2xl bg-[#B00055]/8 text-[#B00055]">
                      <GraduationCap className="size-6" />
                    </span>
                    <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs text-emerald-700">
                      授课中
                    </span>
                  </div>
                  <h3 className="mt-5 truncate text-xl font-semibold group-hover:text-[#B00055]">
                    {course.title}
                  </h3>
                  <p className="mt-2 line-clamp-2 min-h-10 text-sm leading-5 text-slate-500">
                    {course.description ||
                      `${course.subject || '课程'} · ${course.term || '当前学期'}`}
                  </p>
                  <div className="mt-6 grid grid-cols-3 gap-2 text-center">
                    <div className="rounded-xl bg-slate-50 py-3">
                      <b>{course.moduleCount}</b>
                      <p className="text-[10px] text-slate-400">模块</p>
                    </div>
                    <div className="rounded-xl bg-slate-50 py-3">
                      <b>{course.lessonCount}</b>
                      <p className="text-[10px] text-slate-400">课时</p>
                    </div>
                    <div className="rounded-xl bg-slate-50 py-3">
                      <b>{course.studentCount}</b>
                      <p className="text-[10px] text-slate-400">学生</p>
                    </div>
                  </div>
                  <div className="mt-5 flex items-center justify-between border-t pt-4 text-sm">
                    <span className="flex items-center gap-1.5 text-slate-500">
                      <Users className="size-4" />
                      查看资料与学情
                    </span>
                    <ChevronRight className="size-5 text-[#B00055]" />
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
