import { describe, expect, it } from 'vitest';
import JSZip from 'jszip';
import { markdownToArtifactHtml } from '@/lib/course-space/artifact-formats';
import { buildCourseArtifactDocx } from '@/lib/server/course-artifact-docx';

describe('course artifact dual formats', () => {
  it('renders safe structured HTML with source citations', () => {
    const html = markdownToArtifactHtml('# 教学大纲\n\n- **目标** [material:m1 page:2]\n<script>alert(1)</script>');
    expect(html).toContain('<h1>教学大纲</h1>');
    expect(html).toContain('<strong>目标</strong>');
    expect(html).toContain('source-citation');
    expect(html).not.toContain('<script>');
  });

  it('creates a valid editable docx package', async () => {
    const bytes = await buildCourseArtifactDocx('课程教学大纲', '# 第一章\n\n- 教学目标');
    const zip = await JSZip.loadAsync(bytes);
    const documentXml = await zip.file('word/document.xml')!.async('string');
    expect(documentXml).toContain('课程教学大纲');
    expect(documentXml).toContain('教学目标');
    expect(zip.file('word/styles.xml')).toBeTruthy();
  });
});
