'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { suggestRosterLinks, type RosterDirectory, type RosterEntry } from '@/lib/course-space/student-roster';

const fields = [['studentNumber', '学号'], ['name', '姓名'], ['major', '专业'], ['grade', '年级'], ['gender', '性别']] as const;

export function StudentRosterUpload({ courseId, onSaved }: { courseId: string; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [directory, setDirectory] = useState<RosterDirectory>();
  const [entries, setEntries] = useState<RosterEntry[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [saved, setSaved] = useState(false);
  const url = `/api/classes/${encodeURIComponent(courseId)}/student-profiles`;

  async function load(file?: File) {
    setBusy(true); setError(''); setSaved(false);
    setDirectory(undefined); setEntries([]); setWarnings([]);
    try {
      const form = new FormData();
      if (file) form.append('file', file);
      const response = await fetch(url, file ? { method: 'POST', body: form } : { cache: 'no-store' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '读取名单失败');
      setDirectory(data);
      setEntries(file ? suggestRosterLinks(data.imported, data.entries, data.members) : data.entries);
      setWarnings(data.warnings || []);
    } catch (reason) { setError(reason instanceof Error ? reason.message : '读取名单失败'); }
    finally { setBusy(false); }
  }

  async function save() {
    if (!directory) return;
    setBusy(true); setError('');
    try {
      const response = await fetch(url, { method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entries, previous: directory.entries }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '保存名单失败');
      setDirectory({ ...directory, entries: data.entries }); setEntries(data.entries); setSaved(true); onSaved();
    } catch (reason) { setError(reason instanceof Error ? reason.message : '保存名单失败'); }
    finally { setBusy(false); }
  }

  function edit(index: number, field: keyof RosterEntry, value: string) {
    setEntries(rows => rows.map((row, i) => i === index ? { ...row, [field]: field === 'studentId' ? value || null : value } : row));
    setSaved(false);
  }

  return <Dialog open={open} onOpenChange={value => { if (!busy) setOpen(value); }}>
    <Button size="sm" variant="outline" onClick={() => {
      setOpen(true); setDirectory(undefined); setEntries([]); setWarnings([]); void load();
    }}>上传学生名单</Button>
    <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-6xl" showCloseButton={!busy}>
      <DialogTitle>学生名单上传与账号关联</DialogTitle>
      <DialogDescription>上传文字版 PDF，核对信息后确认保存。只关联本课程已选课账号；昵称或重名请手动选择。未注册学生可暂不关联。</DialogDescription>
      <label className="space-y-2 text-sm">选择 PDF（最多 10 MB、50 页）
        <input type="file" accept=".pdf,application/pdf" disabled={busy} className="block w-full rounded border p-2"
          onChange={event => { const file = event.target.files?.[0]; if (file) void load(file); event.target.value = ''; }} />
      </label>
      {busy && <p role="status">正在处理，请稍候…</p>}
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      {warnings.map(warning => <p className="text-sm text-amber-800" key={warning}>{warning}</p>)}
      {directory && <>
        <p className="text-sm">共 {entries.length} 人，待关联 {entries.filter(e => !e.studentId).length} 人。年级可手动补充；重复上传将保留未包含的历史名单。</p>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[850px] text-sm">
            <thead><tr>{fields.map(([, title]) => <th className="p-2 text-left" key={title}>{title}</th>)}<th className="p-2 text-left">注册账号</th><th className="p-2 text-left">本次变化</th></tr></thead>
            <tbody>{entries.map((row, index) => {
              const old = directory.entries.find(e => e.studentNumber === row.studentNumber);
              const changed = !old || [...fields.map(([key]) => key), 'studentId' as const].some(key => old[key] !== row[key]);
              return <tr key={index} className="border-t align-top">
                {fields.map(([field, title]) => <td className="p-1" key={field}>
                  <input aria-label={`第${index + 1}行${title}`} value={row[field]} disabled={busy || (field === 'studentNumber' && Boolean(old))}
                    maxLength={field === 'studentNumber' || field === 'grade' ? 64 : field === 'gender' ? 32 : 255}
                    className="w-full min-w-20 rounded border p-2 disabled:bg-slate-50" onChange={e => edit(index, field, e.target.value)} />
                </td>)}
                <td className="p-1"><select aria-label={`第${index + 1}行注册账号`} value={row.studentId || ''} disabled={busy}
                  className="max-w-64 rounded border p-2" onChange={e => edit(index, 'studentId', e.target.value)}>
                  <option value="">暂不关联</option>
                  {row.studentId && !directory.members.some(m => m.studentId === row.studentId) && <option value={row.studentId}>原账号已退课，请解除关联</option>}
                  {directory.members.map(member => <option key={member.studentId} value={member.studentId}
                    disabled={entries.some((e, i) => i !== index && e.studentId === member.studentId)}>{member.name}{member.email ? `（${member.email}）` : ''}</option>)}
                </select></td>
                <td className="p-2 text-xs">{!old ? '新增' : changed ? '更新' : '无变化'}
                  {changed && old && <p className="mt-1 text-slate-500">原信息：{[old.name, old.major, old.grade || '年级未录入', old.gender,
                    directory.members.find(m => m.studentId === old.studentId)?.name || '未关联'].join(' / ')}</p>}
                </td>
              </tr>;
            })}</tbody>
          </table>
        </div>
        {!entries.length && <p className="text-sm text-slate-500">尚未导入名单，请选择 PDF。</p>}
        <p className="text-xs text-slate-500">保存只更新本课程学生资料，不修改登录账号、选课记录和学习评估。</p>
        {saved && <p role="status" className="text-sm text-green-700">名单已保存，已关联资料可在学生学习详情中查看。</p>}
        <div className="flex justify-end gap-2"><Button variant="outline" disabled={busy} onClick={() => setOpen(false)}>关闭</Button>
          <Button disabled={busy || !entries.length || saved} onClick={() => void save()}>确认关联并保存</Button></div>
      </>}
    </DialogContent>
  </Dialog>;
}
