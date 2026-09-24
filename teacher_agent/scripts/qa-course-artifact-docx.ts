import { promises as fs } from 'fs';
import path from 'path';
import { buildCourseArtifactDocx } from '../lib/server/course-artifact-docx';

async function main() {
  const output = path.join(process.cwd(), 'tmp', 'course-artifact-docx-qa', 'course-outline.docx');
  await fs.mkdir(path.dirname(output), { recursive: true });
  await fs.writeFile(output, await buildCourseArtifactDocx(
    '现代交换原理课程教学大纲',
    '# 课程目标\n\n- 理解交换技术的基本概念\n- 能够比较电路交换与分组交换\n\n## 教学安排\n\n1. 绪论与通信网\n2. 交换技术原理\n\n## 评价方式\n\n形成性评价与期末考核相结合。 [material:demo page:2]',
  ));
  console.log(output);
}

void main();
