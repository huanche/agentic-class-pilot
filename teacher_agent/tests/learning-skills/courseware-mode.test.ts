import { describe, expect, it } from 'vitest';
import {
  buildFaithfulCoursewareRequirement,
  buildLearningSkillsEnhancementRequirement,
  isCoursewareConversionFile,
} from '@/lib/learning-skills/courseware-mode';

describe('courseware conversion modes', () => {
  it('recognizes PPTX and PDF independently of browser MIME quirks', () => {
    expect(isCoursewareConversionFile({ name: 'lesson.PPTX', type: '' })).toBe(true);
    expect(isCoursewareConversionFile({ name: 'handout.bin', type: 'application/pdf' })).toBe(true);
    expect(isCoursewareConversionFile({ name: 'notes.docx' })).toBe(false);
  });

  it('pins the faithful PPT contract to source page count, order and canvas', () => {
    const prompt = buildFaithfulCoursewareRequirement('pptx', 12);
    expect(prompt).toContain('12 页');
    expect(prompt).toContain('审核后保留的页面');
    expect(prompt).toContain('最终场景数必须与审核保留页数一致');
    expect(prompt).toContain('原始相对顺序');
    expect(prompt).toContain('视觉画布');
    expect(prompt).toContain('高亮');
    expect(prompt).toContain('激光笔');
    expect(prompt).toContain('自动播放');
  });

  it('adapts Learning Skills pedagogy without fabricating standards', () => {
    const prompt = buildLearningSkillsEnhancementRequirement('面向初二学生', 'pdf');
    expect(prompt).toContain('面向初二学生');
    expect(prompt).toContain('可测学习目标');
    expect(prompt).toContain('Below / At / Above');
    expect(prompt).toContain('形成性理解检测');
    expect(prompt).toContain('退出任务');
    expect(prompt).toContain('不得虚构课程标准');
    expect(prompt).toContain('数学：');
    expect(prompt).toContain('科学：');
    expect(prompt).toContain('尽量减少教师点击');
  });
});
