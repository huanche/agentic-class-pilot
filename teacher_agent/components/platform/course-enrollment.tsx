 'use client';
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';

export function CourseEnrollment({ courseId }: { courseId: string }) {
  const [code, setCode] = useState('');
  const [message, setMessage] = useState('正在读取选课码…');
  const [standalone, setStandalone] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setCode(''); setMessage('正在读取选课码…');
    fetch(`/api/classes/${encodeURIComponent(courseId)}/enrollment`, { cache: 'no-store', signal: controller.signal })
      .then(async response => {
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || '读取选课码失败');
        setStandalone(Boolean(data.standalone)); setCode(data.enrollCode || ''); setMessage('');
      }).catch(error => { if (!controller.signal.aborted) setMessage(error.message); });
    return () => controller.abort();
  }, [courseId]);
  if (standalone) return null;
  return <section className="rounded-3xl border bg-white p-6 shadow-sm">
    <h2 className="text-lg font-semibold">邀请学生选课</h2>
    <p className="mt-2 text-sm text-slate-500">学生登录平台后，在“加入课程”中填写选课码。授课内容发布后即可进入学习。</p>
    {code && <div className="mt-4 flex items-center gap-4">
      <span className="font-mono text-xl tracking-widest text-[#B00055]">{code}</span>
      <Button variant="outline" onClick={async () => {
        try { await navigator.clipboard.writeText(code); setMessage('已复制'); }
        catch { setMessage('复制失败，请手动复制选课码'); }
      }}>复制选课码</Button>
    </div>}
    {message && <p role="status" className="mt-2 text-sm text-slate-500">{message}</p>}
  </section>;
}
