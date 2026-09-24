import { describe, expect, it } from 'vitest';
import { rankKnowledgeSourceChunks } from '@/lib/server/course-knowledge-extraction';

describe('course knowledge extraction retrieval', () => {
  it('prioritizes chunks matching course structure and objective terms', () => {
    const chunks = [
      { id:'c1', materialId:'m1', materialName:'课程.pptx', page:12,
        text:'附录：设备维护记录', sourceSha256:'hash' },
      { id:'c2', materialId:'m1', materialName:'课程.pptx', page:3,
        text:'课程目标与知识点：理解电路交换和分组交换的基本原理', sourceSha256:'hash' },
      { id:'c3', materialId:'m1', materialName:'课程.pptx', page:8,
        text:'无线传播环境与衰落模型', sourceSha256:'hash' },
    ];
    const ranked = rankKnowledgeSourceChunks(chunks, ['现代交换原理', '电路交换', '课程目标', '无线传播'], 2);
    expect(ranked.map((item) => item.id)).toEqual(['c2', 'c3']);
  });

  it('keeps the requested retrieval limit', () => {
    const chunks = Array.from({ length:10 }, (_, index) => ({ id:`c${index}`, materialId:'m1',
      materialName:'课程.pptx', page:index + 1, text:`第 ${index + 1} 页知识点`, sourceSha256:'hash' }));
    expect(rankKnowledgeSourceChunks(chunks, ['知识点'], 4)).toHaveLength(4);
  });
});
