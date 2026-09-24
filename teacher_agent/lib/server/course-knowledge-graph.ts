import { nanoid } from 'nanoid';
import type {
  CourseKnowledgeEdge,
  CourseKnowledgeGraph,
  CourseKnowledgeNode,
} from '@/lib/course-space/types';
import { readMaterialExtraction, readServerCourse, updateServerCourse } from '@/lib/server/course-space-storage';
import { publishCourseKnowledgeGraphVersion, readCourseKnowledgeGraph, saveCourseKnowledgeGraph } from '@/lib/server/course-knowledge-store';

/**
 * Creates the traceable graph skeleton without inventing concepts. A later
 * extraction job enriches this draft with knowledge-point and alignment nodes.
 */
export async function bootstrapCourseKnowledgeGraph(courseId: string, teacherId: string) {
  const course = await readServerCourse(courseId);
  if (!course) throw new Error('课程不存在');
  if (course.teacherId !== teacherId) throw new Error('无权修改该课程');
  const latest = await readCourseKnowledgeGraph(courseId);
  const version = (latest?.version ?? 0) + 1;
  const now = Date.now();
  const nodes: CourseKnowledgeNode[] = [];
  const edges: CourseKnowledgeEdge[] = [];
  const rootId = `course:${course.id}`;
  nodes.push({ id:rootId, courseId, graphVersion:version, type:'course', title:course.title,
    description:course.description, status:'reviewed', properties:{ subject:course.subject, gradeBand:course.gradeBand, term:course.term },
    evidence:[], createdAt:now, updatedAt:now });

  for (const courseModule of course.modules) {
    const moduleId = `module:${courseModule.id}`;
    nodes.push({ id:moduleId, courseId, graphVersion:version, type:'module', title:courseModule.title,
      moduleId:courseModule.id, status:'reviewed', properties:{ order:courseModule.order, objectives:courseModule.objectives },
      evidence:[], createdAt:now, updatedAt:now });
    edges.push({ id:nanoid(14), courseId, graphVersion:version, sourceNodeId:rootId, targetNodeId:moduleId,
      type:'contains', properties:{}, createdAt:now });
    for (const lesson of courseModule.lessons) {
      const lessonId = `lesson:${lesson.id}`;
      nodes.push({ id:lessonId, courseId, graphVersion:version, type:'lesson', title:lesson.title,
        moduleId:courseModule.id, lessonId:lesson.id, status:'reviewed', properties:{ order:lesson.order, objectives:lesson.objectives },
        evidence:[], createdAt:now, updatedAt:now });
      edges.push({ id:nanoid(14), courseId, graphVersion:version, sourceNodeId:moduleId, targetNodeId:lessonId,
        type:'contains', properties:{}, createdAt:now });
    }
  }

  const extractions = (await Promise.all(course.materials.filter((item) => item.status === 'ready')
    .map((item) => readMaterialExtraction(item.id)))).filter(Boolean);
  for (const extraction of extractions) {
    if (!extraction) continue;
    const material = course.materials.find((item) => item.id === extraction.materialId);
    for (const chunk of extraction.chunks) {
      const nodeId = `source:${chunk.id}`;
      nodes.push({ id:nodeId, courseId, graphVersion:version, type:'source-chunk',
        title:`${material?.name ?? extraction.materialId} · 第 ${chunk.page} 页`,
        description:chunk.text.slice(0, 500), status:'extracted', properties:{ materialId:extraction.materialId, page:chunk.page },
        evidence:[{ id:nanoid(14), courseId, graphVersion:version, nodeId, materialId:extraction.materialId,
          chunkId:chunk.id, page:chunk.page, slide:material?.mimeType.includes('presentation') ? chunk.page : undefined,
          sourceSha256:extraction.sourceSha256, excerpt:chunk.text.slice(0, 280) }], createdAt:now, updatedAt:now });
    }
  }
  const graph: CourseKnowledgeGraph = { courseId, version, status:'draft', title:`${course.title}课程知识图谱`,
    summary:'由课程结构和已解析材料建立的可追溯图谱骨架，等待知识点抽取与教师审核。',
    nodes, edges, sourceMaterialHashes:[...new Set(extractions.map((item) => item!.sourceSha256))],
    createdBy:teacherId, createdAt:now };
  await saveCourseKnowledgeGraph(graph);
  return graph;
}

export async function publishCourseKnowledgeGraph(courseId: string, version: number) {
  const graph = await readCourseKnowledgeGraph(courseId, { version });
  if (!graph) return null;
  if (!graph.nodes.some((node) => node.type === 'source-chunk' && node.evidence.length > 0)) {
    throw new Error('图谱缺少原始材料页码证据，不能发布');
  }
  const reviewNodes = graph.nodes.filter((node) => node.type === 'knowledge-point' || node.type === 'learning-objective');
  if (reviewNodes.length === 0 || reviewNodes.some((node) => node.status !== 'approved')) {
    throw new Error('知识点和课程目标尚未完成教师审核，不能发布');
  }
  const published = await publishCourseKnowledgeGraphVersion(courseId, version);
  if (!published) return null;
  await updateServerCourse(courseId, (course) => ({ ...course, activeKnowledgeGraphVersion:version }));
  return readCourseKnowledgeGraph(courseId, { version });
}
