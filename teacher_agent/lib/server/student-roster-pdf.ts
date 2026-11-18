import { getDocumentProxy } from 'unpdf';
import type { RosterEntry } from '@/lib/course-space/student-roster';

type Word = { text: string; x: number; y: number; width: number };
const compact = (value: string) => value.replace(/\s+/g, '');

/** 按学号所在行和表头列定位，保留跨行姓名，避免把课程编号误识别成学号。 */
export function parseRosterPage(words: Word[]): RosterEntry[] {
  const header = words.find(item => compact(item.text) === '学号');
  const nameHeader = words.find(item => compact(item.text) === '姓名' && (!header || Math.abs(item.y - header.y) < 20));
  if (!header || !nameHeader) throw new Error('未识别到“学号”和“姓名”表头，请上传文字版学生名单 PDF');
  const headers = words.filter(item => Math.abs(item.y - header.y) < 20)
    .map(item => ({ ...item, center: item.x + item.width / 2 }));
  const fields = [
    { key: 'studentNumber', word: header }, { key: 'name', word: nameHeader },
    ...['major', 'gender', 'grade'].flatMap(key => {
      const choices = key === 'major' ? ['专业', '主修专业'] : key === 'gender' ? ['性别', '性'] : ['年级'];
      const word = headers.find(item => choices.includes(compact(item.text)));
      return word ? [{ key, word }] : [];
    }),
  ];
  const center = (word: Word) => word.x + word.width / 2;
  const bounds = (word: Word) => {
    const x = center(word);
    // 专业内容常靠左排列，使用表头之间的空隙分列，避免落入相邻的性别列。
    const left = Math.max(-Infinity, ...headers.filter(h => h.center < x - 1).map(h => h.x + h.width));
    const right = Math.min(Infinity, ...headers.filter(h => h.center > x + 1).map(h => h.x));
    return [(left + word.x) / 2, (right + word.x + word.width) / 2];
  };
  const [left, right] = bounds(header);
  const numbers = words.filter(w => w.y < header.y - 20 && center(w) > left && center(w) < right && /^[A-Za-z0-9-]{5,64}$/.test(compact(w.text)))
    .sort((a, b) => b.y - a.y);
  return numbers.map((number, i) => {
    const top = i ? (numbers[i - 1].y + number.y) / 2 : number.y + 14;
    const bottom = numbers[i + 1] ? (numbers[i + 1].y + number.y) / 2 : number.y - 14;
    const row: RosterEntry = { studentNumber: compact(number.text), name: '', major: '', grade: '', gender: '', studentId: null };
    for (const field of fields.filter(f => f.key !== 'studentNumber')) {
      const [l, r] = bounds(field.word);
      const parts = words.filter(w => w.y < top && w.y > bottom && center(w) > l && center(w) < r)
        .sort((a, b) => Math.abs(a.y - b.y) > 3 ? b.y - a.y : a.x - b.x);
      row[field.key as 'name' | 'major' | 'gender' | 'grade'] = compact(parts.map(p => p.text).join(''));
    }
    if (!row.name) throw new Error(`学号 ${row.studentNumber} 未能提取姓名，请核对 PDF 排版`);
    return row;
  });
}

export async function parseRosterPdf(bytes: Uint8Array) {
  if (bytes.length > 10 * 1024 * 1024) throw new Error('PDF 不能超过 10 MB');
  if (new TextDecoder().decode(bytes.subarray(0, 5)) !== '%PDF-') throw new Error('请选择有效的 PDF 文件');
  const document = await getDocumentProxy(bytes);
  try {
    if (document.numPages > 50) throw new Error('名单 PDF 不能超过 50 页');
    const entries: RosterEntry[] = [];
    let declaredCount: number | undefined;
    for (let page = 1; page <= document.numPages; page++) {
      const content = await (await document.getPage(page)).getTextContent();
      const words = content.items.flatMap(item => 'str' in item && item.str.trim()
        ? [{ text: item.str, x: item.transform[4], y: item.transform[5], width: item.width }] : []);
      const count = words.map(w => compact(w.text)).join(' ').match(/共(\d+)人/);
      if (count) declaredCount = Number(count[1]);
      entries.push(...parseRosterPage(words));
    }
    if (!entries.length) throw new Error('未提取到学生，请使用带可选中文字的 PDF；暂不支持扫描件');
    if (entries.length > 2000) throw new Error('名单最多支持 2000 人');
    if (new Set(entries.map(e => e.studentNumber)).size !== entries.length) throw new Error('PDF 中存在重复学号，请核对后重新上传');
    return { entries, warnings: [
      ...(declaredCount !== undefined && declaredCount !== entries.length ? [`PDF 标注 ${declaredCount} 人，实际提取 ${entries.length} 人，请核对是否遗漏。`] : []),
      ...(entries.some(e => !e.grade) ? ['PDF 未提供部分学生的年级，请手动补充；系统不会根据学号推断。'] : []),
    ] };
  } finally {
    await document.destroy();
  }
}
