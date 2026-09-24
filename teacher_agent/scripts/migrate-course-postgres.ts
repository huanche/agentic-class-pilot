import { promises as fs } from 'node:fs';
import path from 'node:path';
import type {
  CourseArtifactJob,
  CourseArtifactRecord,
  CourseMaterialExtraction,
  CourseSpace,
  PublishedKnowledgePackage,
} from '../lib/course-space/types';
import type { PersistedClassroomData } from '../lib/server/classroom-storage';
import {
  ensureCourseDatabaseSchema,
  isCourseDatabaseConfigured,
  upsertArtifactFileDatabaseRecord,
  upsertClassroomDatabaseRecord,
  upsertCourseArtifactDatabaseRecord,
  upsertCourseDatabaseRecord,
  upsertCourseJobDatabaseRecord,
  upsertCourseMaterialFileDatabaseRecord,
  upsertKnowledgePackageDatabaseRecord,
  upsertMaterialExtractionDatabaseRecord,
} from '../lib/server/course-space-database';
import { createHash } from 'node:crypto';

const root = path.join(process.cwd(), 'data', 'course-spaces');

async function jsonFiles<T>(directory: string): Promise<T[]> {
  try {
    const names = (await fs.readdir(directory)).filter((name) => name.endsWith('.json'));
    return Promise.all(names.map(async (name) => JSON.parse(await fs.readFile(path.join(directory, name), 'utf8')) as T));
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return [];
    throw error;
  }
}

async function main() {
  if (!isCourseDatabaseConfigured()) throw new Error('请先配置 COURSE_DATABASE_URL 或 DATABASE_URL');
  await ensureCourseDatabaseSchema();
  const courses = await jsonFiles<CourseSpace>(path.join(root, 'courses'));
  const artifacts = await jsonFiles<CourseArtifactRecord>(path.join(root, 'artifacts'));
  const jobs = await jsonFiles<CourseArtifactJob>(path.join(root, 'jobs'));
  const knowledgePackages = await jsonFiles<PublishedKnowledgePackage>(path.join(root, 'knowledge-packages'));
  for (const course of courses) await upsertCourseDatabaseRecord(course);
  for (const job of jobs) await upsertCourseJobDatabaseRecord(job);
  for (const pkg of knowledgePackages) await upsertKnowledgePackageDatabaseRecord(pkg);

  let materialCount = 0;
  let extractionCount = 0;
  for (const course of courses) {
    for (const material of course.materials) {
      const sourcePath = path.join(root, 'materials', material.storageKey);
      try {
        const bytes = await fs.readFile(sourcePath);
        await upsertCourseMaterialFileDatabaseRecord({
          storageKey: material.storageKey,
          materialId: material.id,
          courseId: course.id,
          fileName: material.name,
          mimeType: material.mimeType,
          bytes,
          sizeBytes: bytes.length,
          sha256: material.sha256 ?? createHash('sha256').update(bytes).digest('hex'),
        });
        materialCount += 1;
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
        console.warn(`课程材料缺失：${material.storageKey}`);
      }
      const extractionPath = path.join(root, 'materials', material.id, 'extraction.json');
      try {
        const extraction = JSON.parse(await fs.readFile(extractionPath, 'utf8')) as CourseMaterialExtraction;
        await upsertMaterialExtractionDatabaseRecord(extraction);
        extractionCount += 1;
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
      }
    }
  }

  const classroomLinks = new Map(artifacts.filter((item) => item.classroomId).map((item) => [item.classroomId!, item]));
  const classrooms = await jsonFiles<PersistedClassroomData>(path.join(process.cwd(), 'data', 'classrooms'));
  for (const classroom of classrooms) {
    const artifact = classroomLinks.get(classroom.id);
    await upsertClassroomDatabaseRecord(classroom, artifact
      ? { courseId: artifact.courseId, artifactId: artifact.id }
      : {});
  }
  for (const artifact of artifacts) await upsertCourseArtifactDatabaseRecord(artifact);

  let attachmentCount = 0;
  for (const artifact of artifacts) {
    if (!artifact.wordStorageKey) continue;
    const filePath = path.join(root, 'artifact-files', artifact.wordStorageKey);
    try {
      const bytes = await fs.readFile(filePath);
      await upsertArtifactFileDatabaseRecord({
        storageKey: artifact.wordStorageKey,
        artifactId: artifact.id,
        fileName: artifact.wordFileName ?? path.basename(filePath),
        mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        bytes,
        sizeBytes: bytes.length,
        sha256: createHash('sha256').update(bytes).digest('hex'),
      });
      attachmentCount += 1;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
      console.warn(`附件缺失：${artifact.wordStorageKey}`);
    }
  }
  const missingClassrooms = artifacts
    .filter((item) => item.classroomId && !classrooms.some((room) => room.id === item.classroomId))
    .map((item) => ({ artifactId: item.id, classroomId: item.classroomId, title: item.title }));
  console.log(JSON.stringify({ courses: courses.length, materials: materialCount,
    extractions: extractionCount, jobs: jobs.length, artifacts: artifacts.length,
    knowledgePackages: knowledgePackages.length, classrooms: classrooms.length,
    attachments: attachmentCount, missingClassrooms }, null, 2));
}

void main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
