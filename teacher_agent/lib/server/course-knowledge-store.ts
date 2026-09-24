import { promises as fs } from 'node:fs';
import path from 'node:path';
import { writeJsonFileAtomic } from '@/lib/server/classroom-storage';
import type { CourseKnowledgeExtractionJob, CourseKnowledgeGraph } from '@/lib/course-space/types';
import {
  isCourseDatabaseConfigured,
  listCourseKnowledgeExtractionJobs as listDatabaseJobs,
  publishCourseKnowledgeGraphInDatabase,
  readCourseKnowledgeExtractionJob as readDatabaseJob,
  readCourseKnowledgeGraphFromDatabase,
  saveCourseKnowledgeGraphToDatabase,
  upsertCourseKnowledgeExtractionJob as saveDatabaseJob,
} from '@/lib/server/course-space-database';

const ROOT = process.env.COURSE_SPACES_DATA_DIR
  ? path.resolve(process.env.COURSE_SPACES_DATA_DIR)
  : path.join(process.cwd(), 'data', 'course-spaces');
const GRAPH_DIR = path.join(ROOT, 'knowledge-graphs');
const JOB_DIR = path.join(ROOT, 'knowledge-graph-jobs');

function assertId(value: string, label: string) {
  if (!/^[a-zA-Z0-9_-]+$/.test(value)) throw new Error(`Invalid ${label}`);
}

async function readJson<T>(file: string): Promise<T | null> {
  try { return JSON.parse(await fs.readFile(file, 'utf8')) as T; }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null;
    throw error;
  }
}

async function listJson<T>(directory: string): Promise<T[]> {
  try {
    const files = (await fs.readdir(directory)).filter((name) => name.endsWith('.json'));
    const values = await Promise.all(files.map((name) => readJson<T>(path.join(directory, name))));
    return values.reduce<T[]>((items, value) => value === null ? items : [...items, value], []);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return [];
    throw error;
  }
}

function graphFile(courseId: string, version: number) {
  assertId(courseId, 'course id');
  return path.join(GRAPH_DIR, courseId, `v${version}.json`);
}

export function getKnowledgeGraphStorageMode() {
  return isCourseDatabaseConfigured() ? 'postgresql' as const : 'local-json' as const;
}

export async function readCourseKnowledgeGraph(
  courseId: string,
  options: { version?: number; publishedOnly?: boolean } = {},
) {
  if (isCourseDatabaseConfigured()) return readCourseKnowledgeGraphFromDatabase(courseId, options);
  assertId(courseId, 'course id');
  const graphs = await listJson<CourseKnowledgeGraph>(path.join(GRAPH_DIR, courseId));
  return graphs
    .filter((graph) => options.version ? graph.version === options.version : true)
    .filter((graph) => options.publishedOnly ? graph.status === 'published' : true)
    .sort((a, b) => b.version - a.version)[0] ?? null;
}

export async function saveCourseKnowledgeGraph(graph: CourseKnowledgeGraph) {
  if (isCourseDatabaseConfigured()) return saveCourseKnowledgeGraphToDatabase(graph);
  await writeJsonFileAtomic(graphFile(graph.courseId, graph.version), graph);
  return graph;
}

export async function publishCourseKnowledgeGraphVersion(courseId: string, version: number) {
  if (isCourseDatabaseConfigured()) return publishCourseKnowledgeGraphInDatabase(courseId, version);
  const graphs = await listJson<CourseKnowledgeGraph>(path.join(GRAPH_DIR, courseId));
  const target = graphs.find((graph) => graph.version === version);
  if (!target) return false;
  const publishedAt = Date.now();
  await Promise.all(graphs.map((graph) => saveCourseKnowledgeGraph({
    ...graph,
    status: graph.version === version ? 'published' : graph.status === 'published' ? 'superseded' : graph.status,
    publishedAt: graph.version === version ? publishedAt : graph.publishedAt,
  })));
  return true;
}

export async function saveCourseKnowledgeExtractionJob(job: CourseKnowledgeExtractionJob) {
  if (isCourseDatabaseConfigured()) return saveDatabaseJob(job);
  assertId(job.id, 'knowledge job id');
  await writeJsonFileAtomic(path.join(JOB_DIR, `${job.id}.json`), job);
}

export async function readCourseKnowledgeExtractionJob(jobId: string) {
  if (isCourseDatabaseConfigured()) return readDatabaseJob(jobId);
  assertId(jobId, 'knowledge job id');
  return readJson<CourseKnowledgeExtractionJob>(path.join(JOB_DIR, `${jobId}.json`));
}

export async function listCourseKnowledgeExtractionJobs(courseId: string) {
  if (isCourseDatabaseConfigured()) return (await listDatabaseJobs(courseId)) ?? [];
  return (await listJson<CourseKnowledgeExtractionJob>(JOB_DIR))
    .filter((job) => job.courseId === courseId)
    .sort((a, b) => b.createdAt - a.createdAt);
}
