#!/usr/bin/env tsx
/**
 * 课程存储迁移脚本：从文件系统迁移到 PostgreSQL
 *
 * 用法:
 *   pnpm tsx scripts/migrate-course-storage.ts [--dry-run] [--course-id <id>]
 *
 * 选项:
 *   --dry-run        只显示要迁移的内容，不实际执行迁移
 *   --course-id <id> 只迁移指定课程（默认迁移所有课程）
 *   --force          强制覆盖已存在的记录
 *   --verify         迁移后验证数据一致性
 */

import { promises as fs } from 'fs';
import path from 'path';
import {
  getCourseDatabasePool,
  isCourseDatabaseConfigured,
} from '@/lib/server/course-space-database';
import type {
  CourseSpace,
  CourseMaterialExtraction,
  CourseArtifactJob,
  CourseArtifactRecord,
} from '@/lib/course-space/types';

const COURSE_SPACES_DIR = process.env.COURSE_SPACES_DATA_DIR
  ? path.resolve(process.env.COURSE_SPACES_DATA_DIR)
  : path.join(process.cwd(), 'data', 'course-spaces');

interface MigrationStats {
  courses: number;
  materials: number;
  jobs: number;
  artifacts: number;
  errors: Array<{ file: string; error: string }>;
}

async function readJsonFile<T>(filePath: string): Promise<T | null> {
  try {
    const content = await fs.readFile(filePath, 'utf8');
    return JSON.parse(content) as T;
  } catch (error) {
    if ((error as any).code === 'ENOENT') return null;
    throw error;
  }
}

async function readDirectory(dir: string): Promise<string[]> {
  try {
    return await fs.readdir(dir);
  } catch (error) {
    if ((error as any).code === 'ENOENT') return [];
    throw error;
  }
}

async function migrateCourses(dryRun: boolean, courseId?: string): Promise<MigrationStats> {
  const stats: MigrationStats = { courses: 0, materials: 0, jobs: 0, artifacts: 0, errors: [] };

  const coursesDir = path.join(COURSE_SPACES_DIR, 'courses');
  const courseFiles = await readDirectory(coursesDir);

  for (const file of courseFiles) {
    if (!file.endsWith('.json')) continue;

    const course = await readJsonFile<CourseSpace>(path.join(coursesDir, file));
    if (!course) continue;
    if (courseId && course.id !== courseId) continue;

    if (!dryRun) {
      try {
        const pool = getCourseDatabasePool();
        if (!pool) throw new Error('数据库连接未配置');

        const client = await pool.connect();
        try {
          await client.query(
            `INSERT INTO mentra_courses (id, teacher_id, status, title, payload, created_at, updated_at)
             VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7)
             ON CONFLICT (id) DO UPDATE SET teacher_id=EXCLUDED.teacher_id, status=EXCLUDED.status,
               title=EXCLUDED.title, payload=EXCLUDED.payload, updated_at=EXCLUDED.updated_at`,
            [
              course.id,
              course.teacherId,
              course.status,
              course.title,
              JSON.stringify(course),
              course.createdAt,
              course.updatedAt,
            ],
          );
        } finally {
          client.release();
        }
      } catch (error) {
        stats.errors.push({
          file: file,
          error: error instanceof Error ? error.message : String(error),
        });
        console.error(`❌ 迁移课程 ${course.id} 失败:`, error);
        continue;
      }
    }

    console.log(`✓ 课程: ${course.id} (${course.title})`);
    stats.courses++;
  }

  return stats;
}

async function migrateMaterials(dryRun: boolean, courseId?: string): Promise<MigrationStats> {
  const stats: MigrationStats = { courses: 0, materials: 0, jobs: 0, artifacts: 0, errors: [] };

  const materialsDir = path.join(COURSE_SPACES_DIR, 'materials');
  const materialDirs = await readDirectory(materialsDir);

  for (const materialId of materialDirs) {
    const extractionFile = path.join(materialsDir, materialId, 'extraction.json');
    const extraction = await readJsonFile<CourseMaterialExtraction>(extractionFile);

    if (!extraction) continue;
    if (courseId && extraction.courseId !== courseId) continue;

    if (!dryRun) {
      try {
        const pool = getCourseDatabasePool();
        if (!pool) throw new Error('数据库连接未配置');

        const client = await pool.connect();
        try {
          await client.query(
            `INSERT INTO mentra_material_extractions (material_id, course_id, source_sha256, payload, created_at, updated_at)
             VALUES ($1,$2,$3,$4::jsonb,$5,$6)
             ON CONFLICT (material_id) DO UPDATE SET course_id=EXCLUDED.course_id,
               source_sha256=EXCLUDED.source_sha256, payload=EXCLUDED.payload, updated_at=EXCLUDED.updated_at`,
            [
              extraction.materialId,
              extraction.courseId,
              extraction.sourceSha256,
              JSON.stringify(extraction),
              extraction.createdAt,
              Date.now(),
            ],
          );
        } finally {
          client.release();
        }
      } catch (error) {
        stats.errors.push({
          file: extractionFile,
          error: error instanceof Error ? error.message : String(error),
        });
        console.error(`❌ 迁移材料提取 ${materialId} 失败:`, error);
        continue;
      }
    }

    console.log(`✓ 材料提取: ${materialId}`);
    stats.materials++;
  }

  return stats;
}

async function migrateJobs(dryRun: boolean, courseId?: string): Promise<MigrationStats> {
  const stats: MigrationStats = { courses: 0, materials: 0, jobs: 0, artifacts: 0, errors: [] };

  const jobsDir = path.join(COURSE_SPACES_DIR, 'jobs');
  const jobFiles = await readDirectory(jobsDir);

  for (const file of jobFiles) {
    if (!file.endsWith('.json')) continue;

    const job = await readJsonFile<CourseArtifactJob>(path.join(jobsDir, file));
    if (!job) continue;
    if (courseId && job.courseId !== courseId) continue;

    if (!dryRun) {
      try {
        const pool = getCourseDatabasePool();
        if (!pool) throw new Error('数据库连接未配置');

        const client = await pool.connect();
        try {
          await client.query(
            `INSERT INTO mentra_artifact_jobs (id, course_id, teacher_id, artifact_type, status, payload, created_at, updated_at)
             VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8)
             ON CONFLICT (id) DO UPDATE SET status=EXCLUDED.status, payload=EXCLUDED.payload,
               artifact_type=EXCLUDED.artifact_type, updated_at=EXCLUDED.updated_at`,
            [
              job.id,
              job.courseId,
              job.teacherId,
              job.artifactType,
              job.status,
              JSON.stringify(job),
              job.createdAt,
              job.updatedAt,
            ],
          );
        } finally {
          client.release();
        }
      } catch (error) {
        stats.errors.push({
          file: file,
          error: error instanceof Error ? error.message : String(error),
        });
        console.error(`❌ 迁移任务 ${job.id} 失败:`, error);
        continue;
      }
    }

    console.log(`✓ 任务: ${job.id}`);
    stats.jobs++;
  }

  return stats;
}

async function migrateArtifacts(dryRun: boolean, courseId?: string): Promise<MigrationStats> {
  const stats: MigrationStats = { courses: 0, materials: 0, jobs: 0, artifacts: 0, errors: [] };

  const artifactsDir = path.join(COURSE_SPACES_DIR, 'artifacts');
  const artifactFiles = await readDirectory(artifactsDir);

  for (const file of artifactFiles) {
    if (!file.endsWith('.json')) continue;

    const artifact = await readJsonFile<CourseArtifactRecord>(path.join(artifactsDir, file));
    if (!artifact) continue;
    if (courseId && artifact.courseId !== courseId) continue;

    if (!dryRun) {
      try {
        const pool = getCourseDatabasePool();
        if (!pool) throw new Error('数据库连接未配置');

        const client = await pool.connect();
        try {
          await client.query(
            `INSERT INTO mentra_course_artifacts (id, job_id, course_id, teacher_id, artifact_type, status, payload, created_at, updated_at)
             VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9)
             ON CONFLICT (id) DO UPDATE SET status=EXCLUDED.status, payload=EXCLUDED.payload,
               artifact_type=EXCLUDED.artifact_type, updated_at=EXCLUDED.updated_at`,
            [
              artifact.id,
              artifact.jobId,
              artifact.courseId,
              artifact.teacherId,
              artifact.type,
              artifact.status,
              JSON.stringify(artifact),
              artifact.createdAt,
              artifact.updatedAt,
            ],
          );
        } finally {
          client.release();
        }
      } catch (error) {
        stats.errors.push({
          file: file,
          error: error instanceof Error ? error.message : String(error),
        });
        console.error(`❌ 迁移产物 ${artifact.id} 失败:`, error);
        continue;
      }
    }

    console.log(`✓ 产物: ${artifact.id}`);
    stats.artifacts++;
  }

  return stats;
}

async function main() {
  const args = process.argv.slice(2);
  const dryRun = args.includes('--dry-run');
  const courseId = args[args.indexOf('--course-id') + 1];

  console.log('🔄 课程存储迁移');
  console.log(`📁 数据目录: ${COURSE_SPACES_DIR}`);
  console.log(`模式: ${dryRun ? '预演(不写入)' : '实际迁移'}`);
  if (courseId) console.log(`课程 ID: ${courseId}`);

  if (!isCourseDatabaseConfigured()) {
    console.error('❌ 错误：未配置 COURSE_DATABASE_URL 或 DATABASE_URL');
    console.error('请在 .env.local 中设置数据库连接');
    process.exit(1);
  }

  console.log('✓ 数据库已配置\n');

  try {
    console.log('📚 迁移课程...');
    const courseStats = await migrateCourses(dryRun, courseId);

    console.log('📄 迁移材料提取...');
    const materialStats = await migrateMaterials(dryRun, courseId);

    console.log('⚙️  迁移任务...');
    const jobStats = await migrateJobs(dryRun, courseId);

    console.log('🎁 迁移产物...');
    const artifactStats = await migrateArtifacts(dryRun, courseId);

    const totalStats = {
      courses:
        courseStats.courses + materialStats.courses + jobStats.courses + artifactStats.courses,
      materials:
        courseStats.materials +
        materialStats.materials +
        jobStats.materials +
        artifactStats.materials,
      jobs: courseStats.jobs + materialStats.jobs + jobStats.jobs + artifactStats.jobs,
      artifacts:
        courseStats.artifacts +
        materialStats.artifacts +
        jobStats.artifacts +
        artifactStats.artifacts,
      errors: [
        ...courseStats.errors,
        ...materialStats.errors,
        ...jobStats.errors,
        ...artifactStats.errors,
      ],
    };

    console.log('\n📊 迁移摘要');
    console.log('='.repeat(50));
    console.log(`课程数: ${courseStats.courses}`);
    console.log(`材料提取数: ${materialStats.materials}`);
    console.log(`任务数: ${jobStats.jobs}`);
    console.log(`产物数: ${artifactStats.artifacts}`);

    if (totalStats.errors.length > 0) {
      console.log(`\n⚠️  错误数: ${totalStats.errors.length}`);
      totalStats.errors.forEach((err) => {
        console.log(`  - ${err.file}: ${err.error}`);
      });
    }

    if (dryRun) {
      console.log('\n✅ 预演完成，未进行实际迁移');
      console.log('运行 "pnpm tsx scripts/migrate-course-storage.ts" 开始实际迁移');
    } else {
      console.log('\n✅ 迁移完成！');
    }
  } catch (error) {
    console.error('❌ 迁移失败:', error);
    process.exit(1);
  }
}

main();
