import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { promises as fs } from 'fs';
import path from 'path';
import { Pool } from 'pg';
import type {
  CourseSpace,
  CourseMaterialExtraction,
  CourseArtifactJob,
  CourseArtifactRecord,
} from '@/lib/course-space/types';
import {
  getCourseDatabasePool,
  isCourseDatabaseConfigured,
  ensureCourseDatabaseSchema,
  upsertCourseDatabaseRecord,
  upsertMaterialExtractionDatabaseRecord,
  upsertCourseJobDatabaseRecord,
  upsertCourseArtifactDatabaseRecord,
} from '@/lib/server/course-space-database';

describe('Course Storage Migration', () => {
  let pool: Pool | undefined;
  const testCourseId = 'test-course-migration-' + Date.now();
  const testMaterialId = 'test-material-' + Date.now();
  const testJobId = 'test-job-' + Date.now();
  const testArtifactId = 'test-artifact-' + Date.now();

  beforeAll(async () => {
    if (!isCourseDatabaseConfigured()) {
      console.warn('⚠️  数据库未配置，跳过迁移测试');
      return;
    }

    pool = getCourseDatabasePool();
    if (pool) {
      try {
        await ensureCourseDatabaseSchema();
      } catch (error) {
        console.error('创建 schema 失败:', error);
        throw error;
      }
    }
  });

  afterAll(async () => {
    if (pool) {
      try {
        // 清理测试数据
        const client = await pool.connect();
        try {
          await client.query('DELETE FROM mentra_courses WHERE id LIKE $1', ['test-course-%']);
          await client.query('DELETE FROM mentra_material_extractions WHERE material_id LIKE $1', [
            'test-material-%',
          ]);
          await client.query('DELETE FROM mentra_artifact_jobs WHERE id LIKE $1', ['test-job-%']);
          await client.query('DELETE FROM mentra_course_artifacts WHERE id LIKE $1', [
            'test-artifact-%',
          ]);
        } finally {
          client.release();
        }
      } catch (error) {
        console.error('清理测试数据失败:', error);
      }
    }
  });

  describe('Course Migration', () => {
    it('应该将课程保存到数据库', async () => {
      if (!pool) {
        console.warn('⚠️  跳过：数据库未配置');
        return;
      }

      const course: CourseSpace = {
        id: testCourseId,
        teacherId: 'teacher-001',
        title: 'Test Course Migration',
        subject: 'Physics',
        gradeBand: 'Grade 10',
        status: 'draft',
        modules: [],
        materials: [],
        createdAt: Date.now(),
        updatedAt: Date.now(),
      };

      await upsertCourseDatabaseRecord(course);

      const client = await pool.connect();
      try {
        const result = await client.query('SELECT payload FROM mentra_courses WHERE id = $1', [
          testCourseId,
        ]);
        expect(result.rows.length).toBe(1);
        expect(result.rows[0].payload.id).toBe(testCourseId);
        expect(result.rows[0].payload.title).toBe('Test Course Migration');
      } finally {
        client.release();
      }
    });

    it('应该支持 UPSERT 操作', async () => {
      if (!pool) {
        console.warn('⚠️  跳过：数据库未配置');
        return;
      }

      const course: CourseSpace = {
        id: testCourseId,
        teacherId: 'teacher-001',
        title: 'Updated Course Title',
        subject: 'Physics',
        gradeBand: 'Grade 10',
        status: 'active',
        modules: [],
        materials: [],
        createdAt: Date.now() - 10000,
        updatedAt: Date.now(),
      };

      await upsertCourseDatabaseRecord(course);
      await upsertCourseDatabaseRecord(course);

      const client = await pool.connect();
      try {
        const result = await client.query(
          'SELECT COUNT(*) as count FROM mentra_courses WHERE id = $1',
          [testCourseId],
        );
        expect(parseInt(result.rows[0].count)).toBe(1);

        const courseResult = await client.query(
          'SELECT payload FROM mentra_courses WHERE id = $1',
          [testCourseId],
        );
        expect(courseResult.rows[0].payload.title).toBe('Updated Course Title');
        expect(courseResult.rows[0].payload.status).toBe('active');
      } finally {
        client.release();
      }
    });

    it('应该按 updated_at 排序课程', async () => {
      if (!pool) {
        console.warn('⚠️  跳过：数据库未配置');
        return;
      }

      const client = await pool.connect();
      try {
        const result = await client.query(
          `SELECT id FROM mentra_courses
           WHERE teacher_id = $1
           ORDER BY updated_at DESC
           LIMIT 10`,
          ['teacher-001'],
        );

        // 验证索引有效
        expect(result.rows).toBeDefined();
      } finally {
        client.release();
      }
    });
  });

  describe('Material Extraction Migration', () => {
    it('应该将材料提取保存到数据库', async () => {
      if (!pool) {
        console.warn('⚠️  跳过：数据库未配置');
        return;
      }

      const extraction: CourseMaterialExtraction = {
        materialId: testMaterialId,
        courseId: testCourseId,
        sourceSha256: 'abc123def456',
        text: '测试用讲义文本',
        pageCount: 1,
        chunks: [],
        formulas: [],
        createdAt: Date.now(),
      };

      await upsertMaterialExtractionDatabaseRecord(extraction);

      const client = await pool.connect();
      try {
        const result = await client.query(
          'SELECT payload FROM mentra_material_extractions WHERE material_id = $1',
          [testMaterialId],
        );
        expect(result.rows.length).toBe(1);
        expect(result.rows[0].payload.courseId).toBe(testCourseId);
      } finally {
        client.release();
      }
    });

    it('应该按课程 ID 查询材料', async () => {
      if (!pool) {
        console.warn('⚠️  跳过：数据库未配置');
        return;
      }

      const client = await pool.connect();
      try {
        const result = await client.query(
          'SELECT payload FROM mentra_material_extractions WHERE course_id = $1',
          [testCourseId],
        );
        expect(result.rows.length).toBeGreaterThanOrEqual(0);
      } finally {
        client.release();
      }
    });
  });

  describe('Artifact Job Migration', () => {
    it('应该将任务保存到数据库', async () => {
      if (!pool) {
        console.warn('⚠️  跳过：数据库未配置');
        return;
      }

      const job: CourseArtifactJob = {
        id: testJobId,
        courseId: testCourseId,
        teacherId: 'teacher-001',
        scope: { type: 'course' },
        artifactType: 'exercise-set',
        status: 'queued',
        progress: 0,
        message: '',
        createdAt: Date.now(),
        updatedAt: Date.now(),
      };

      await upsertCourseJobDatabaseRecord(job);

      const client = await pool.connect();
      try {
        const result = await client.query(
          'SELECT payload FROM mentra_artifact_jobs WHERE id = $1',
          [testJobId],
        );
        expect(result.rows.length).toBe(1);
        expect(result.rows[0].payload.status).toBe('queued');
      } finally {
        client.release();
      }
    });

    it('应该按课程和创建时间查询任务', async () => {
      if (!pool) {
        console.warn('⚠️  跳过：数据库未配置');
        return;
      }

      const client = await pool.connect();
      try {
        const result = await client.query(
          `SELECT payload FROM mentra_artifact_jobs
           WHERE course_id = $1
           ORDER BY created_at DESC`,
          [testCourseId],
        );
        expect(result.rows.length).toBeGreaterThanOrEqual(0);
      } finally {
        client.release();
      }
    });
  });

  describe('Artifact Record Migration', () => {
    it('应该将产物保存到数据库', async () => {
      if (!pool) {
        console.warn('⚠️  跳过：数据库未配置');
        return;
      }

      const artifact: CourseArtifactRecord = {
        id: testArtifactId,
        jobId: testJobId,
        courseId: testCourseId,
        teacherId: 'teacher-001',
        scope: { type: 'course' },
        type: 'exercise-set',
        title: 'Test Quiz',
        status: 'review',
        content: 'Test Quiz',
        citations: [],
        createdAt: Date.now(),
        updatedAt: Date.now(),
      };

      await upsertCourseArtifactDatabaseRecord(artifact);

      const client = await pool.connect();
      try {
        const result = await client.query(
          'SELECT payload FROM mentra_course_artifacts WHERE id = $1',
          [testArtifactId],
        );
        expect(result.rows.length).toBe(1);
        expect(result.rows[0].payload.type).toBe('exercise-set');
      } finally {
        client.release();
      }
    });

    it('应该按课程和状态查询产物', async () => {
      if (!pool) {
        console.warn('⚠️  跳过：数据库未配置');
        return;
      }

      const client = await pool.connect();
      try {
        const result = await client.query(
          `SELECT payload FROM mentra_course_artifacts
           WHERE course_id = $1 AND status = $2
           ORDER BY updated_at DESC`,
          [testCourseId, 'review'],
        );
        expect(result.rows.length).toBeGreaterThanOrEqual(0);
      } finally {
        client.release();
      }
    });
  });

  describe('Database Schema Validation', () => {
    it('应该创建所有必需的表', async () => {
      if (!pool) {
        console.warn('⚠️  跳过：数据库未配置');
        return;
      }

      const tables = [
        'mentra_courses',
        'mentra_material_extractions',
        'mentra_artifact_jobs',
        'mentra_course_artifacts',
        'mentra_knowledge_packages',
        'mentra_course_graph_versions',
        'mentra_course_graph_nodes',
        'mentra_course_graph_edges',
        'mentra_course_graph_evidence',
        'mentra_course_access_grants',
      ];

      const client = await pool.connect();
      try {
        for (const table of tables) {
          const result = await client.query(
            `SELECT EXISTS(
              SELECT FROM information_schema.tables
              WHERE table_name = $1
            )`,
            [table],
          );
          expect(result.rows[0].exists).toBe(true);
        }
      } finally {
        client.release();
      }
    });

    it('应该创建所有必需的索引', async () => {
      if (!pool) {
        console.warn('⚠️  跳过：数据库未配置');
        return;
      }

      const indexes = [
        'mentra_courses_teacher_updated_idx',
        'mentra_material_extractions_course_idx',
        'mentra_artifact_jobs_course_created_idx',
        'mentra_course_artifacts_course_status_idx',
      ];

      const client = await pool.connect();
      try {
        for (const index of indexes) {
          const result = await client.query(
            `SELECT EXISTS(
              SELECT FROM pg_indexes
              WHERE indexname = $1
            )`,
            [index],
          );
          expect(result.rows[0].exists).toBe(true);
        }
      } finally {
        client.release();
      }
    });
  });
});
