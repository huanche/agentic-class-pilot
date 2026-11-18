import { expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { parseRosterPage, parseRosterPdf } from '@/lib/server/student-roster-pdf';
import { suggestRosterLinks } from '@/lib/course-space/student-roster';

const word = (text: string, x: number, y: number, width = 20) => ({ text, x, y, width });
it('extracts a wrapped name and leaves absent grade blank', () => {
  const rows = parseRosterPage([
    word('序号', 0, 700), word('学号', 60, 700), word('姓名', 120, 700),
    word('性', 154, 705, 11), word('别', 154, 695, 11), word('主修专业', 186, 700, 45),
    word('1', 0, 650), word('202400001', 40, 650, 50), word('测试·', 110, 655, 35),
    word('同学', 120, 644), word('女', 154, 650, 9), word('通信工程', 167, 650, 27),
  ]);
  expect(rows).toEqual([{ studentNumber: '202400001', name: '测试·同学', gender: '女', major: '通信工程', grade: '', studentId: null }]);
});
it('rejects a page with no recognizable table and invalid PDF bytes', async () => {
  expect(() => parseRosterPage([word('图片', 0, 0)])).toThrow('表头');
  await expect(parseRosterPdf(new TextEncoder().encode('not pdf'))).rejects.toThrow('有效的 PDF');
});
const entry = (name: string, number: string) => ({ name, studentNumber: number, grade: '', major: '', gender: '', studentId: null });
it('suggests unique exact names but not nickname or duplicate names', () => {
  const rows = suggestRosterLinks([entry('张 同学', '1'), entry('李同学', '2'), entry('王同学', '3')], [],
    [{ studentId: 'a', name: '张同学' }, { studentId: 'b', name: 'nickname' }, { studentId: 'c', name: '王同学' }, { studentId: 'd', name: '王同学' }]);
  expect(rows.map(r => r.studentId)).toEqual(['a', null, null]);
});
it('retains prior rows, manual grade and links across repeated uploads', () => {
  const saved = [{ ...entry('张同学', '1'), studentId: 'a', grade: '2024级' }, entry('待注册', '2')];
  expect(suggestRosterLinks([entry('张同学', '1')], saved, [])).toEqual(saved);
});
it('does not assign one account to two equal names in the PDF', () => {
  expect(suggestRosterLinks([entry('张同学', '1'), entry('张同学', '2')], [], [{ studentId: 'a', name: '张同学' }])
    .every(r => r.studentId === null)).toBe(true);
});

it('preserves a manual unlink and never displaces an existing link', () => {
  const saved = [{ ...entry('原姓名', '1'), studentId: 'a' }, entry('李同学', '2')];
  const rows = suggestRosterLinks([entry('张同学', '3'), entry('李同学', '2')], saved,
    [{ studentId: 'a', name: '张同学' }, { studentId: 'b', name: '李同学' }]);
  expect(rows.find(r => r.studentNumber === '1')?.studentId).toBe('a');
  expect(rows.find(r => r.studentNumber === '2')?.studentId).toBeNull();
  expect(rows.find(r => r.studentNumber === '3')?.studentId).toBeNull();
});

// 实际名单只从测试环境读取，不把学生个人资料提交到代码仓库。
it.skipIf(!process.env.ROSTER_PDF_FIXTURE)('extracts the supplied two-page roster', async () => {
  const result = await parseRosterPdf(new Uint8Array(readFileSync(process.env.ROSTER_PDF_FIXTURE!)));
  expect(result.entries).toHaveLength(37);
  expect(result.entries.every(row => row.name && row.studentNumber && row.major && ['男', '女'].includes(row.gender))).toBe(true);
  expect(result.entries.every(row => !row.grade)).toBe(true);
}, 30000);
