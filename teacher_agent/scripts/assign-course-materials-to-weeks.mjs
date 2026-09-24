import { readFile, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';

const courseId = process.argv[2] || 'sx2QQqfZUm48';
if (!/^[A-Za-z0-9_-]+$/.test(courseId)) throw new Error('课程 ID 格式不合法');

const coursePath = path.resolve('data', 'course-spaces', 'courses', `${courseId}.json`);
const temporaryPath = `${coursePath}.${process.pid}.tmp`;
const course = JSON.parse(await readFile(coursePath, 'utf8'));

function chapterNumber(name) {
  const match = name.match(/第\s*(\d+)\s*章/);
  return match ? Number(match[1]) : undefined;
}

const assignments = course.materials
  .map((material) => ({ material, week: chapterNumber(material.name) }))
  .filter((item) => item.week && item.week >= 1 && item.week <= 15);

let linked = 0;
const now = Date.now();
for (const module of course.modules) {
  for (const lesson of module.lessons) {
    const match = lesson.title.match(/^第\s*(\d+)\s*周$/);
    if (!match) continue;
    const week = Number(match[1]);
    const materialIds = assignments
      .filter((item) => item.week === week)
      .map((item) => item.material.id);
    if (materialIds.length === 0) continue;
    const previous = Array.isArray(lesson.materialIds) ? lesson.materialIds : [];
    lesson.materialIds = [...new Set([...previous, ...materialIds])];
    linked += lesson.materialIds.length - previous.length;
    lesson.updatedAt = now;
  }
}
course.updatedAt = now;

await writeFile(temporaryPath, `${JSON.stringify(course, null, 2)}\n`, 'utf8');
await rename(temporaryPath, coursePath);

console.log(`课程 ${courseId} 已新增 ${linked} 条周课时—PPT 材料关联。`);
for (const item of assignments) console.log(`第${item.week}周 <- ${item.material.name}`);
