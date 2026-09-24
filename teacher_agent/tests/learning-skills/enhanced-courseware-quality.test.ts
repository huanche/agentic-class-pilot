import { describe, expect, it } from 'vitest';
import {
  LEARNING_SKILLS_ENHANCED_MARKER,
  removeTeacherOnlyNotices,
  withEnhancedChoreographyContract,
} from '@/lib/learning-skills/enhanced-courseware-quality';

const outline = {
  id: 'scene-1',
  type: 'slide' as const,
  title: '无线电波传播',
  description: `${LEARNING_SKILLS_ENHANCED_MARKER}\n解释传播机制`,
  keyPoints: ['传播机制'],
  order: 1,
};

describe('AI-enhanced courseware quality contract', () => {
  it('removes teacher-only governance notices from the student canvas', () => {
    const content = removeTeacherOnlyNotices({
      elements: [
        { id: 'lesson', type: 'text', content: '<p>电磁波通过空间传播</p>' },
        {
          id: 'notice',
          type: 'text',
          content: '本课内容重建自教师上传 PPT，未添加外部课程标准；建议教师复核。',
        },
        { id: 'diagram', type: 'shape', shape: 'rect' },
      ] as any,
    });

    expect(content.elements.map((element) => element.id)).toEqual(['lesson', 'diagram']);
  });

  it('requires visual target and following speech to describe the same knowledge point', () => {
    const enhanced = withEnhancedChoreographyContract(outline);

    expect(enhanced.description).toContain('先 spotlight 或 laser');
    expect(enhanced.description).toContain('再立即播报');
    expect(enhanced.description).toContain('禁止讲解 A 时高亮 B');
    expect(enhanced.description).toContain('不要高亮背景');
    expect(enhanced.description).toContain('主体知识点全部讲完后生成 reveal');
    expect(enhanced.description).toContain('再紧接 speech 解释结论');
  });

  it('does not alter an ordinary non-enhanced outline', () => {
    const faithful = { ...outline, description: '高保真路径' };
    expect(withEnhancedChoreographyContract(faithful)).toBe(faithful);
  });
});
