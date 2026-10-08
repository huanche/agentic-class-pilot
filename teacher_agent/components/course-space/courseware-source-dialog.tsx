'use client';

import * as React from 'react';
import type { CourseSpace, CourseMaterialRecord } from '@/lib/course-space';

async function readTeacherPptResponse(response: Response) {
  const body = await response.json();
  if (!response.ok || body.success === false) throw new Error(body.error || `HTTP ${response.status}`);
  return body;
}

/** Explicit teacher-PPT entry; chat generation never opens this dialog. */
export function CoursewareSourceDialog({ course, onCancel, onSelect }: {
  course: CourseSpace;
  onCancel: () => void;
  onSelect: (material: CourseMaterialRecord) => void | Promise<void>;
}) {
  const [materials, setMaterials] = React.useState(course.materials.filter(item => /\.pptx?$/i.test(item.name)));
  const [selectedId, setSelectedId] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [progress, setProgress] = React.useState('');
  const [error, setError] = React.useState('');
  const controller = React.useRef<AbortController | null>(null);
  const panel = React.useRef<HTMLDivElement | null>(null);
  React.useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    return () => { controller.current?.abort(); previous?.focus(); };
  }, []);
  const close = () => { controller.current?.abort(); onCancel(); };
  const prepare = async (material: CourseMaterialRecord, signal: AbortSignal) => {
    if (material.status === 'ready') return material;
    setProgress('正在解析课件，请稍候…');
    const url = `/api/course-space/${encodeURIComponent(course.id)}`;
    await readTeacherPptResponse(await fetch(`${url}/materials/${encodeURIComponent(material.id)}/parse`, { method: 'POST', signal }));
    for (let attempt = 0; attempt < 120; attempt++) {
      await new Promise<void>((resolve, reject) => {
        const stop = () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); };
        const timer = setTimeout(() => { signal.removeEventListener('abort', stop); resolve(); }, 1500);
        if (signal.aborted) stop(); else signal.addEventListener('abort', stop, { once: true });
      });
      const data = await readTeacherPptResponse(await fetch(url, { cache: 'no-store', signal }));
      const found = data.course?.materials.find((item: CourseMaterialRecord) => item.id === material.id);
      if (found?.status === 'ready') return found as CourseMaterialRecord;
      if (found?.status === 'failed') throw new Error('课件解析失败，请重新选择文件或稍后重试。');
    }
    throw new Error('课件已保存，解析仍在进行。请稍后从课程中的课件列表选择并继续。');
  };
  const run = async (action: (signal: AbortSignal) => Promise<void>) => {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setBusy(true); setError('');
    try { await action(current.signal); }
    catch (e) { if (!current.signal.aborted) setError(e instanceof Error ? e.message : String(e)); }
    finally { if (!current.signal.aborted) { setBusy(false); setProgress(''); } }
  };
  const upload = (file?: File) => {
    if (!file) return;
    if (!/\.pptx?$/i.test(file.name)) { setError('请选择 PPT 或 PPTX 文件。'); return; }
    if (file.size > 80 * 1024 * 1024) { setError('课件不能超过 80MB。'); return; }
    void run(async signal => {
      setProgress('正在上传课件…');
      const form = new FormData(); form.append('file', file);
      const data = await readTeacherPptResponse(await fetch(`/api/course-space/${encodeURIComponent(course.id)}/materials`, { method: 'POST', body: form, signal }));
      const material = data.material as CourseMaterialRecord;
      setMaterials(previous => [...previous.filter(item => item.id !== material.id), material]);
      setSelectedId(material.id);
      const ready = await prepare(material, signal);
      setMaterials(previous => previous.map(item => item.id === ready.id ? ready : item));
    });
  };
  const next = () => {
    const material = materials.find(item => item.id === selectedId);
    if (!material) return;
    void run(async signal => { const ready = await prepare(material, signal); if (!signal.aborted) await onSelect(ready); });
  };
  const buttonStyle: React.CSSProperties = { padding: '10px 18px', borderRadius: 12, border: '1px solid #ead6e0', cursor: busy ? 'wait' : 'pointer' };
  return <div style={{ position: 'fixed', inset: 0, zIndex: 80, background: '#0f172a66', display: 'grid', placeItems: 'center', padding: 20 }} onMouseDown={event => { if (event.target === event.currentTarget) close(); }}>
    <div ref={panel} role="dialog" aria-modal="true" aria-labelledby="teacher-ppt-source-title" tabIndex={-1}
      style={{ background: 'white', color: '#172033', borderRadius: 22, padding: 28, maxWidth: 620, width: '100%', maxHeight: '90vh', overflowY: 'auto', boxShadow: '0 24px 80px #17203333' }}
      onKeyDown={event => {
        if (event.key === 'Escape') { event.stopPropagation(); close(); }
        if (event.key === 'Tab') {
          const elements = panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled)');
          if (!elements?.length) return;
          const first = elements[0], last = elements[elements.length - 1];
          if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) { event.preventDefault(); last.focus(); }
          else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
        }
      }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}><h2 id="teacher-ppt-source-title" style={{ fontSize: 22, fontWeight: 700 }}>选择讲师 PPT</h2><button type="button" aria-label="关闭课件选择" onClick={close} style={buttonStyle}>×</button></div>
      <p style={{ margin: '12px 0 24px', color: '#64748b', lineHeight: 1.7 }}>先上传或选择要转换的课件，再选择高保真还原或 AI 增强。此入口不会自动创建 AI 生成任务。</p>
      <label style={{ display: 'block', padding: 20, border: '1px dashed #c54f86', borderRadius: 14, background: '#fff8fb' }}>上传新的课件（PPT / PPTX，最大 80MB）
        <input aria-label="上传讲师课件" type="file" accept=".ppt,.pptx" disabled={busy} style={{ display: 'block', marginTop: 14, maxWidth: '100%' }} onChange={event => { upload(event.target.files?.[0]); event.target.value = ''; }} />
      </label>
      <label style={{ display: 'block', marginTop: 22 }}>或选择课程中的课件
        <select aria-label="课程中的课件" disabled={busy} value={selectedId} onChange={event => setSelectedId(event.target.value)} style={{ display: 'block', width: '100%', marginTop: 10, border: '1px solid #cbd5e1', borderRadius: 10, padding: 10 }}>
          <option value="">请选择课件</option>{materials.map(item => <option key={item.id} value={item.id}>{item.name}{item.status === 'ready' ? '' : '（待解析）'}</option>)}
        </select>
      </label>
      <p style={{ color: '#64748b', fontSize: 13, marginTop: 16 }}>高保真还原请优先上传 PPTX；旧版 PPT 可使用 AI 增强，或另存为 PPTX 后再上传。</p>
      {progress && <p role="status" style={{ marginTop: 14 }}>{progress}</p>}
      {error && <p role="alert" style={{ marginTop: 14, color: '#b91c1c' }}>{error}</p>}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12, marginTop: 24 }}><button type="button" style={buttonStyle} onClick={close}>取消</button><button type="button" disabled={busy || !selectedId} onClick={next} style={{ ...buttonStyle, background: '#b00055', color: 'white', opacity: busy || !selectedId ? .5 : 1 }}>下一步：选择转换方式</button></div>
    </div>
  </div>;
}
