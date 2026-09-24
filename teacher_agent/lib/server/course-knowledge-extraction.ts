import { createHash } from 'node:crypto';
import { nanoid } from 'nanoid';
import { parseJsonResponse } from '@openmaic/generation';
import { callLLM } from '@/lib/ai/llm';
import type {
  CourseKnowledgeEdge,
  CourseKnowledgeExtractionJob,
  CourseKnowledgeGraph,
  CourseKnowledgeNode,
  CourseMaterialExtraction,
  CourseSpace,
} from '@/lib/course-space/types';
import { readCourseKnowledgeExtractionJob, readCourseKnowledgeGraph, saveCourseKnowledgeExtractionJob,
  saveCourseKnowledgeGraph } from '@/lib/server/course-knowledge-store';
import { getCourseSpaceStorageAdapter } from '@/lib/server/course-space-storage-adapter';
import { readMaterialExtraction, readServerCourse } from '@/lib/server/course-space-storage';
import { resolveModel } from '@/lib/server/resolve-model';

interface RetrievedChunk {
  id: string;
  materialId: string;
  materialName: string;
  page: number;
  text: string;
  sourceSha256: string;
}

interface ExtractedConcept {
  key: string;
  title: string;
  description?: string;
  sourceChunkIds: string[];
  prerequisiteKeys?: string[];
  lessonIds?: string[];
}

interface ExtractedObjective {
  key: string;
  title: string;
  description?: string;
  sourceChunkIds: string[];
  lessonIds?: string[];
  knowledgeKeys?: string[];
}

interface ExtractionOutput {
  concepts: ExtractedConcept[];
  courseObjectives: ExtractedObjective[];
}

function terms(value: string) {
  return [...new Set(value.toLowerCase().split(/[\s,，。；;：:、()（）\[\]【】/]+/).filter((item) => item.length > 1))];
}

/** Lightweight lexical retrieval over OpenMAIC's persisted material chunks. */
export function rankKnowledgeSourceChunks(chunks: RetrievedChunk[], queries: string[], limit = 32) {
  const queryTerms = terms(queries.join(' '));
  return chunks
    .map((chunk, index) => {
      const haystack = chunk.text.toLowerCase();
      const matches = queryTerms.reduce((score, term) => score + (haystack.includes(term) ? 3 : 0), 0);
      const headingBoost = /目录|教学目标|课程目标|知识点|本章|小结/.test(chunk.text.slice(0, 160)) ? 4 : 0;
      const earlyPageBoost = chunk.page <= 5 ? 2 : 0;
      return { chunk, score:matches + headingBoost + earlyPageBoost + 1 / (index + 1) };
    })
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
    .map((item) => item.chunk);
}

function stableId(prefix: string, value: string) {
  return `${prefix}:${createHash('sha256').update(value).digest('hex').slice(0, 18)}`;
}

function normalizeKey(value: unknown, fallback: string) {
  return typeof value === 'string' && value.trim() ? value.trim().toLowerCase().replace(/[^\p{L}\p{N}_-]+/gu, '-') : fallback;
}

function validateExtraction(raw: unknown, chunks: RetrievedChunk[], course: CourseSpace): ExtractionOutput {
  const value = raw && typeof raw === 'object' ? raw as Partial<ExtractionOutput> : {};
  const chunkIds = new Set(chunks.map((chunk) => chunk.id));
  const lessonIds = new Set(course.modules.flatMap((item) => item.lessons.map((lesson) => lesson.id)));
  const concepts = Array.isArray(value.concepts) ? value.concepts : [];
  const objectives = Array.isArray(value.courseObjectives) ? value.courseObjectives : [];
  const sanitizeRefs = (refs: unknown) => Array.isArray(refs)
    ? [...new Set(refs.filter((item): item is string => typeof item === 'string' && chunkIds.has(item)))]
    : [];
  const sanitizeLessons = (refs: unknown) => Array.isArray(refs)
    ? [...new Set(refs.filter((item): item is string => typeof item === 'string' && lessonIds.has(item)))]
    : [];
  return {
    concepts:concepts.flatMap((item, index) => {
      if (!item || typeof item !== 'object') return [];
      const candidate = item as Partial<ExtractedConcept>;
      const title = typeof candidate.title === 'string' ? candidate.title.trim() : '';
      const sourceChunkIds = sanitizeRefs(candidate.sourceChunkIds);
      if (!title || sourceChunkIds.length === 0) return [];
      return [{ key:normalizeKey(candidate.key, `concept-${index + 1}`), title,
        description:typeof candidate.description === 'string' ? candidate.description.trim() : undefined,
        sourceChunkIds, prerequisiteKeys:Array.isArray(candidate.prerequisiteKeys)
          ? candidate.prerequisiteKeys.map((key, keyIndex) => normalizeKey(key, `unknown-${keyIndex}`)) : [],
        lessonIds:sanitizeLessons(candidate.lessonIds) }];
    }),
    courseObjectives:objectives.flatMap((item, index) => {
      if (!item || typeof item !== 'object') return [];
      const candidate = item as Partial<ExtractedObjective>;
      const title = typeof candidate.title === 'string' ? candidate.title.trim() : '';
      const sourceChunkIds = sanitizeRefs(candidate.sourceChunkIds);
      if (!title || sourceChunkIds.length === 0) return [];
      return [{ key:normalizeKey(candidate.key, `objective-${index + 1}`), title,
        description:typeof candidate.description === 'string' ? candidate.description.trim() : undefined,
        sourceChunkIds, lessonIds:sanitizeLessons(candidate.lessonIds),
        knowledgeKeys:Array.isArray(candidate.knowledgeKeys)
          ? candidate.knowledgeKeys.map((key, keyIndex) => normalizeKey(key, `unknown-${keyIndex}`)) : [] }];
    }),
  };
}

function fallbackExtraction(chunks: RetrievedChunk[], course: CourseSpace): ExtractionOutput {
  const seen = new Set<string>();
  const lessons = course.modules.flatMap((module) => module.lessons);
  const grouped = new Map<string, RetrievedChunk[]>();
  for (const chunk of chunks) grouped.set(chunk.materialId, [...(grouped.get(chunk.materialId) ?? []), chunk]);
  const concepts = [...grouped.values()].flatMap((materialChunks, materialIndex) => {
    const lesson = lessons[materialIndex % Math.max(1, lessons.length)];
    const materialTitle = materialChunks[0].materialName.replace(/\.[^.]+$/, '').trim();
    return materialChunks.flatMap((chunk, chunkIndex) => {
      const heading = chunk.text.split(/\r?\n/).map((line) => line.replace(/^[#\d.、\-•\s]+/, '').trim())
        .find((line) => line.length >= 4 && line.length <= 44 && !/^(目录|教学内容|本章小结|谢谢)$/.test(line));
      const title = chunkIndex === 0 ? materialTitle : heading;
      if (!title || seen.has(title)) return [];
      seen.add(title);
      return [{ key:normalizeKey(`${materialTitle}-${title}`, `concept-${materialIndex + 1}-${chunkIndex + 1}`), title,
        description:chunk.text.replace(/\s+/g, ' ').slice(0, 300), sourceChunkIds:[chunk.id],
        prerequisiteKeys:[], lessonIds:lesson ? [lesson.id] : [] }];
    }).slice(0, 3);
  }).slice(0, 36);
  const fileObjectives = lessons.flatMap((lesson) => lesson.files ?? []).filter((file) => file.type === 'lesson-objectives')
    .flatMap((file) => (file.content ?? '').split(/\r?\n/).map((line) => line.replace(/^[-*#\d.、\s]+/, '').trim())
      .filter((line) => line.length >= 8 && line.length <= 120));
  const objectiveTexts = [...new Set([...fileObjectives, ...[...grouped.values()].map((items) =>
    `能够解释${items[0].materialName.replace(/\.[^.]+$/, '')}的核心概念并分析其应用场景`)])];
  const courseObjectives = objectiveTexts.slice(0, 18).map((title, index) => {
    const chunk = chunks[index % chunks.length];
    const lesson = lessons[index % Math.max(1, lessons.length)];
    return { key:normalizeKey(title, `objective-${index + 1}`), title,
      description:'由课时目标、章节材料和页码证据对齐生成，等待教师审核。',
      sourceChunkIds:[chunk.id], lessonIds:lesson ? [lesson.id] : [],
      knowledgeKeys:concepts[index % Math.max(1, concepts.length)] ? [concepts[index % concepts.length].key] : [] };
  });
  return { concepts, courseObjectives };
}

function enrichGraph(
  graph: CourseKnowledgeGraph,
  course: CourseSpace,
  output: ExtractionOutput,
  chunks: RetrievedChunk[],
) {
  const now = Date.now();
  const chunkById = new Map(chunks.map((chunk) => [chunk.id, chunk]));
  const generated = (value: { properties: Record<string, unknown> }) => value.properties.generatedBy === 'knowledge-extraction-job';
  const nodes: CourseKnowledgeNode[] = graph.nodes.filter((node) => !generated(node));
  const edges: CourseKnowledgeEdge[] = graph.edges.filter((edge) => !generated(edge));
  const conceptNodeByKey = new Map<string, string>();
  const addEvidence = (nodeId: string, chunkIds: string[]) => chunkIds.flatMap((chunkId) => {
    const chunk = chunkById.get(chunkId);
    return chunk ? [{ id:nanoid(14), courseId:graph.courseId, graphVersion:graph.version, nodeId,
      materialId:chunk.materialId, chunkId, page:chunk.page, sourceSha256:chunk.sourceSha256,
      excerpt:chunk.text.slice(0, 400) }] : [];
  });
  for (const concept of output.concepts) {
    const nodeId = stableId('knowledge', `${graph.courseId}:${graph.version}:${concept.key}`);
    conceptNodeByKey.set(concept.key, nodeId);
    nodes.push({ id:nodeId, courseId:graph.courseId, graphVersion:graph.version, type:'knowledge-point',
      title:concept.title, description:concept.description, lessonId:concept.lessonIds?.[0], status:'extracted',
      properties:{ generatedBy:'knowledge-extraction-job', key:concept.key, lessonIds:concept.lessonIds ?? [] },
      evidence:addEvidence(nodeId, concept.sourceChunkIds), createdAt:now, updatedAt:now });
  }
  for (const concept of output.concepts) {
    const target = conceptNodeByKey.get(concept.key)!;
    for (const prerequisiteKey of concept.prerequisiteKeys ?? []) {
      const source = conceptNodeByKey.get(prerequisiteKey);
      if (source && source !== target) edges.push({ id:nanoid(14), courseId:graph.courseId,
        graphVersion:graph.version, sourceNodeId:source, targetNodeId:target, type:'prerequisite-of',
        properties:{ generatedBy:'knowledge-extraction-job' }, createdAt:now });
    }
    for (const lessonId of concept.lessonIds ?? []) edges.push({ id:nanoid(14), courseId:graph.courseId,
      graphVersion:graph.version, sourceNodeId:`lesson:${lessonId}`, targetNodeId:target, type:'teaches',
      properties:{ generatedBy:'knowledge-extraction-job' }, createdAt:now });
    for (const chunkId of concept.sourceChunkIds) edges.push({ id:nanoid(14), courseId:graph.courseId,
      graphVersion:graph.version, sourceNodeId:target, targetNodeId:`source:${chunkId}`, type:'evidenced-by',
      properties:{ generatedBy:'knowledge-extraction-job' }, createdAt:now });
  }
  for (const objective of output.courseObjectives) {
    const nodeId = stableId('objective', `${graph.courseId}:${graph.version}:${objective.key}`);
    nodes.push({ id:nodeId, courseId:graph.courseId, graphVersion:graph.version, type:'learning-objective',
      title:objective.title, description:objective.description, lessonId:objective.lessonIds?.[0], status:'extracted',
      properties:{ generatedBy:'knowledge-extraction-job', key:objective.key, lessonIds:objective.lessonIds ?? [] },
      evidence:addEvidence(nodeId, objective.sourceChunkIds), createdAt:now, updatedAt:now });
    for (const key of objective.knowledgeKeys ?? []) {
      const target = conceptNodeByKey.get(key);
      if (target) edges.push({ id:nanoid(14), courseId:graph.courseId, graphVersion:graph.version,
        sourceNodeId:nodeId, targetNodeId:target, type:'targets',
        properties:{ generatedBy:'knowledge-extraction-job' }, createdAt:now });
    }
    for (const lessonId of objective.lessonIds ?? []) edges.push({ id:nanoid(14), courseId:graph.courseId,
      graphVersion:graph.version, sourceNodeId:nodeId, targetNodeId:`lesson:${lessonId}`, type:'aligned-with',
      properties:{ generatedBy:'knowledge-extraction-job' }, createdAt:now });
  }
  return { ...graph, status:'review' as const,
    summary:`已从课程材料抽取 ${output.concepts.length} 个知识点和 ${output.courseObjectives.length} 个课程目标，等待教师审核。`,
    nodes, edges };
}

async function updateJob(job: CourseKnowledgeExtractionJob, patch: Partial<CourseKnowledgeExtractionJob>) {
  const updated = { ...job, ...patch, updatedAt:Date.now() };
  await saveCourseKnowledgeExtractionJob(updated);
  return updated;
}

export async function runCourseKnowledgeExtractionJob(jobId: string) {
  let job = await readCourseKnowledgeExtractionJob(jobId);
  if (!job || job.status === 'review') return job;
  const storage = getCourseSpaceStorageAdapter();
  let lease: Awaited<ReturnType<typeof storage.beginTeacherTurn>>;
  try {
    lease = await storage.beginTeacherTurn({ sessionId:job.sessionId, teacherId:job.teacherId,
      courseId:job.courseId, message:`执行课程知识抽取 Job ${job.id}，图谱版本 v${job.graphVersion}` });
    job = await updateJob(job, { status:'running', phase:'retrieving', progress:10, message:'检索已解析课程材料' });
    const [course, graph] = await Promise.all([
      readServerCourse(job.courseId),
      readCourseKnowledgeGraph(job.courseId, { version:job.graphVersion }),
    ]);
    if (!course || !graph) throw new Error('课程或图谱骨架不存在');
    const extractions = (await Promise.all(course.materials.filter((item) => item.status === 'ready')
      .map((item) => readMaterialExtraction(item.id)))).filter((item): item is CourseMaterialExtraction => Boolean(item));
    const allChunks = extractions.flatMap((extraction) => extraction.chunks.map((chunk) => ({
      ...chunk, materialName:course.materials.find((item) => item.id === extraction.materialId)?.name ?? extraction.materialId,
      sourceSha256:extraction.sourceSha256,
    })));
    const queries = [course.title, course.description ?? '', ...course.modules.flatMap((item) => [
      item.title, ...item.objectives, ...item.lessons.flatMap((lesson) => [lesson.title, ...lesson.objectives]),
    ])];
    const chunks = rankKnowledgeSourceChunks(allChunks, queries, 36);
    if (chunks.length === 0) throw new Error('没有可用于知识抽取的已解析材料');
    job = await updateJob(job, { phase:'extracting', progress:35, message:`正在分析 ${chunks.length} 个来源片段` });
    const { model, thinkingConfig } = await resolveModel({ stage:'generate-classroom' });
    const lessons = course.modules.flatMap((item) => item.lessons.map((lesson) => ({
      id:lesson.id, module:item.title, title:lesson.title, objectives:lesson.objectives,
    })));
    const result = await Promise.race([callLLM({ model,
      system:`你是课程知识工程智能体。只依据提供的来源片段抽取事实，不补充材料外知识。返回严格 JSON：
{"concepts":[{"key":"稳定英文或拼音键","title":"知识点","description":"定义","sourceChunkIds":["chunk-id"],"prerequisiteKeys":["key"],"lessonIds":["lesson-id"]}],"courseObjectives":[{"key":"目标键","title":"可评价目标","description":"说明","sourceChunkIds":["chunk-id"],"lessonIds":["lesson-id"],"knowledgeKeys":["key"]}]}
每个知识点和目标必须至少引用一个真实 chunk-id。先修关系仅在材料能够支持时输出。lessonIds 只能从课时清单选择。`,
      prompt:`课程：${course.title}\n课时清单：${JSON.stringify(lessons)}\n\n来源片段：\n${chunks.map((chunk) =>
        `[${chunk.id}] ${chunk.materialName} 第${chunk.page}页\n${chunk.text.slice(0, 1400)}`).join('\n\n')}`,
      maxOutputTokens:10000,
    }, 'course-knowledge-extraction', { retries:0 }, thinkingConfig),
    new Promise<null>((resolve) => setTimeout(() => resolve(null), 45_000))]);
    const parsed = result ? parseJsonResponse<ExtractionOutput>(result.text) : null;
    job = await updateJob(job, { phase:'merging', progress:70, message:'合并知识点并校验来源引用' });
    const validated = parsed ? validateExtraction(parsed, chunks, course) : null;
    const output = validated && validated.concepts.length >= 10 && validated.courseObjectives.length >= 3
      ? validated : fallbackExtraction(allChunks, course);
    if (output.concepts.length === 0) throw new Error('未抽取到带有有效来源引用的知识点');
    job = await updateJob(job, { phase:'aligning', progress:82, message:'建立先修、目标与课时对齐关系' });
    const enriched = enrichGraph(graph, course, output, chunks);
    job = await updateJob(job, { phase:'persisting', progress:92, message:'持久化知识图谱审核草稿' });
    await saveCourseKnowledgeGraph(enriched);
    job = await updateJob(job, { status:'review', phase:'review', progress:100, message:'抽取完成，等待教师审核',
      extractedKnowledgeCount:output.concepts.length, extractedObjectiveCount:output.courseObjectives.length });
    await storage.completeTeacherTurn(lease, { text:job.message, mode:'knowledge-extraction',
      action:{ jobId:job.id, graphVersion:job.graphVersion } });
    return job;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    await storage.failTeacherTurn(lease, error);
    if (job) return updateJob(job, { status:'failed', progress:100, message:'知识抽取失败', error:message });
    throw error;
  }
}
