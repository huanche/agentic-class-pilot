'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowLeft, FolderPlus, Layers3, Plus, Upload } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ApiCourseSpaceRepository, DEFAULT_TEACHER_ID, type CourseSpace } from '@/lib/course-space';
import { platformHomeUrl } from '@/lib/integration/platform-links';

export function CourseCenter() {
  const router = useRouter();
  const repository = useMemo(() => new ApiCourseSpaceRepository(), []);
  const [courses, setCourses] = useState<CourseSpace[]>([]);
  const [title, setTitle] = useState('');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    void repository.listByTeacher(DEFAULT_TEACHER_ID).then(setCourses).catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)));
  }, [repository]);

  const createCourse = async () => {
    if (!title.trim() || creating) return;
    try {
      setCreating(true);
      const course = await repository.create({ teacherId: DEFAULT_TEACHER_ID, title: title.trim() });
      router.push(`/course-space/${course.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setCreating(false);
    }
  };

  return <main className="min-h-screen bg-[radial-gradient(circle_at_22%_5%,rgba(59,130,246,0.12),transparent_30%),radial-gradient(circle_at_80%_90%,rgba(176,0,85,0.10),transparent_34%),#f7f9fc] text-slate-900">
    <header className="flex items-center justify-between border-b border-white/80 bg-white/75 px-7 py-4 backdrop-blur-xl">
      <div className="flex items-center gap-3"><Button variant="ghost" size="icon" className="rounded-full" aria-label="返回管理平台" onClick={() => window.location.assign(platformHomeUrl())}><ArrowLeft/></Button><img src="/mentra-icon.svg" alt="MENTRA" className="size-10"/><div><h1 className="text-xl font-semibold">课程中心</h1><p className="text-xs text-muted-foreground">管理完整课程体系与教师智能体工作区</p></div></div>
      <div className="rounded-full border bg-white px-4 py-2 text-xs text-muted-foreground">默认教师 · {courses.length} 门课程</div>
    </header>
    <section className="mx-auto max-w-[1440px] px-7 py-8">
      <div className="mb-6 flex items-end justify-between"><div><h2 className="text-3xl font-semibold tracking-tight">我的课程</h2><p className="mt-1.5 text-sm text-muted-foreground">点击课程先查看建设状态，再进入教师课程工作区。</p></div></div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">{courses.map((course) => {
        const lessons = course.modules.reduce((sum, module) => sum + module.lessons.length, 0);
        const ready = course.materials.filter((material) => material.status === 'ready').length;
        return <button key={course.id} onClick={() => router.push(`/course-space/${course.id}`)} className="group min-h-[270px] overflow-hidden rounded-[20px] border border-white/80 bg-white/90 text-left shadow-[0_16px_42px_-34px_rgba(15,23,42,0.5)] transition hover:-translate-y-1 hover:border-[#B00055]/25 hover:shadow-[0_22px_55px_-34px_rgba(176,0,85,0.28)]"><div className="h-1.5 bg-gradient-to-r from-[#B00055] via-[#D65A93] to-blue-400"/><div className="p-5"><div className="flex items-start justify-between"><div className="rounded-xl bg-[#B00055]/8 p-2.5 text-[#B00055]"><Layers3 className="size-5"/></div><span className={`rounded-full px-2.5 py-1 text-[11px] ${course.status === 'active' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>{course.status === 'active' ? '已发布' : '建设中'}</span></div><h3 className="mt-4 truncate text-lg font-semibold group-hover:text-[#8F0046]">{course.title}</h3><p className="mt-1 line-clamp-2 min-h-9 text-xs leading-[18px] text-muted-foreground">{course.description || `${course.subject || '课程'}的完整教学资源与智能体工作空间`}</p><div className="mt-4 grid grid-cols-3 gap-1.5 text-center"><div className="rounded-lg bg-slate-50 px-1 py-2"><b className="text-sm">{course.modules.length}</b><p className="text-[10px] text-muted-foreground">模块</p></div><div className="rounded-lg bg-slate-50 px-1 py-2"><b className="text-sm">{lessons}</b><p className="text-[10px] text-muted-foreground">课时</p></div><div className="rounded-lg bg-slate-50 px-1 py-2"><b className="text-sm">{ready}/{course.materials.length}</b><p className="text-[10px] text-muted-foreground">已解析材料</p></div></div><div className="mt-4 flex items-center justify-between border-t pt-3 text-[11px] text-muted-foreground"><span><Upload className="mr-1 inline size-3"/>{course.materials.length ? '已有课程材料' : '待上传材料'}</span><span className="font-medium text-[#B00055]">查看状态 →</span></div></div></button>;
      })}
        <div className="flex min-h-[270px] flex-col rounded-[20px] border-2 border-dashed border-[#B00055]/20 bg-white/55 p-5 shadow-[0_16px_42px_-36px_rgba(15,23,42,0.35)] transition hover:border-[#B00055]/40 hover:bg-white/80">
          <div className="flex items-center gap-2.5"><div className="rounded-xl bg-[#B00055]/10 p-2.5 text-[#B00055]"><FolderPlus className="size-5"/></div><div><h3 className="text-base font-semibold">添加新课程</h3><p className="mt-0.5 text-[11px] text-muted-foreground">创建独立的课程空间</p></div></div>
          <div className="mt-5 flex flex-1 flex-col justify-center"><Input value={title} onChange={(event) => setTitle(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void createCourse(); }} placeholder="输入课程名称" className="h-10 rounded-xl bg-white text-sm"/><Button className="mt-2.5 h-10 rounded-xl bg-[#B00055] text-sm hover:bg-[#8F0046]" disabled={!title.trim() || creating} onClick={() => void createCourse()}><Plus className="mr-1 size-4"/>{creating ? '正在创建…' : '创建课程'}</Button></div>
          <p className="mt-4 text-[11px] leading-[18px] text-muted-foreground">创建后不会自动生成内容，可进入课程上传材料并选择生成产物。</p>
        </div>
      </div>
      {error && <div className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>}
    </section>
  </main>;
}
