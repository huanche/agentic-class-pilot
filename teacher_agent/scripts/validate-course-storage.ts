#!/usr/bin/env tsx
/**
 * 课程数据验证和导出脚本
 *
 * 用法:
 *   pnpm tsx scripts/validate-course-storage.ts [--export] [--report]
 *
 * 选项:
 *   --export <dir>  导出数据到指定目录（JSON 格式）
 *   --report        生成验证报告
 */

import {
  getCourseDatabasePool,
  isCourseDatabaseConfigured,
} from '@/lib/server/course-space-database';
import { promises as fs } from 'fs';
import path from 'path';

interface ValidationReport {
  timestamp: string;
  database: {
    configured: boolean;
    connected: boolean;
    database?: string;
    error?: string;
  };
  statistics: {
    courses: number;
    materials: number;
    jobs: number;
    artifacts: number;
    knowledgePackages: number;
  };
  integrity: {
    orphanedMaterials: Array<{ materialId: string; courseId: string }>;
    orphanedJobs: Array<{ jobId: string; courseId: string }>;
    orphanedArtifacts: Array<{ artifactId: string; courseId: string }>;
    brokenReferences: string[];
  };
  performance: {
    indexExists: Record<string, boolean>;
    estimatedTableSizes: Record<string, number>;
  };
}

async function validateDatabase(): Promise<ValidationReport> {
  const report: ValidationReport = {
    timestamp: new Date().toISOString(),
    database: { configured: false, connected: false },
    statistics: { courses: 0, materials: 0, jobs: 0, artifacts: 0, knowledgePackages: 0 },
    integrity: {
      orphanedMaterials: [],
      orphanedJobs: [],
      orphanedArtifacts: [],
      brokenReferences: [],
    },
    performance: { indexExists: {}, estimatedTableSizes: {} },
  };

  if (!isCourseDatabaseConfigured()) {
    report.database.configured = false;
    return report;
  }

  report.database.configured = true;

  const pool = getCourseDatabasePool();
  if (!pool) {
    report.database.error = '无法获取连接池';
    return report;
  }

  const client = await pool.connect();
  try {
    // 测试连接
    try {
      const result = await client.query(
        'SELECT current_database() AS database, NOW() AS checked_at',
      );
      report.database.connected = true;
      report.database.database = result.rows[0].database;
    } catch (error) {
      report.database.connected = false;
      report.database.error = error instanceof Error ? error.message : String(error);
      return report;
    }

    // 收集统计信息
    const tables = {
      mentra_courses: 'courses',
      mentra_material_extractions: 'materials',
      mentra_artifact_jobs: 'jobs',
      mentra_course_artifacts: 'artifacts',
      mentra_knowledge_packages: 'knowledgePackages',
    };

    for (const [table, key] of Object.entries(tables)) {
      try {
        const result = await client.query(`SELECT COUNT(*) as count FROM ${table}`);
        report.statistics[key as keyof typeof report.statistics] = parseInt(result.rows[0].count);
      } catch (error) {
        console.warn(`无法计算 ${table} 数量:`, error);
      }
    }

    // 检查数据完整性
    // 孤立的材料记录
    try {
      const result = await client.query(`
        SELECT m.material_id, m.course_id
        FROM mentra_material_extractions m
        LEFT JOIN mentra_courses c ON m.course_id = c.id
        WHERE c.id IS NULL
      `);
      report.integrity.orphanedMaterials = result.rows;
    } catch (error) {
      console.warn('无法检查孤立材料:', error);
    }

    // 孤立的任务记录
    try {
      const result = await client.query(`
        SELECT j.id as jobId, j.course_id as courseId
        FROM mentra_artifact_jobs j
        LEFT JOIN mentra_courses c ON j.course_id = c.id
        WHERE c.id IS NULL
      `);
      report.integrity.orphanedJobs = result.rows;
    } catch (error) {
      console.warn('无法检查孤立任务:', error);
    }

    // 孤立的产物记录
    try {
      const result = await client.query(`
        SELECT a.id as artifactId, a.course_id as courseId
        FROM mentra_course_artifacts a
        LEFT JOIN mentra_courses c ON a.course_id = c.id
        WHERE c.id IS NULL
      `);
      report.integrity.orphanedArtifacts = result.rows;
    } catch (error) {
      console.warn('无法检查孤立产物:', error);
    }

    // 检查索引
    const indexes = [
      'mentra_courses_teacher_updated_idx',
      'mentra_material_extractions_course_idx',
      'mentra_artifact_jobs_course_created_idx',
      'mentra_course_artifacts_course_status_idx',
      'mentra_knowledge_packages_course_status_idx',
    ];

    for (const index of indexes) {
      try {
        const result = await client.query(
          `SELECT EXISTS(SELECT FROM pg_indexes WHERE indexname = $1)`,
          [index],
        );
        report.performance.indexExists[index] = result.rows[0].exists;
      } catch (error) {
        report.performance.indexExists[index] = false;
      }
    }

    // 估算表大小
    for (const table of Object.keys(tables)) {
      try {
        const result = await client.query(`SELECT pg_total_relation_size($1) as size`, [table]);
        report.performance.estimatedTableSizes[table] = parseInt(result.rows[0].size);
      } catch (error) {
        console.warn(`无法计算 ${table} 大小:`, error);
      }
    }
  } finally {
    client.release();
  }

  return report;
}

async function exportData(exportDir: string): Promise<void> {
  console.log(`📤 导出数据到: ${exportDir}`);

  if (!isCourseDatabaseConfigured()) {
    console.error('❌ 数据库未配置');
    return;
  }

  await fs.mkdir(exportDir, { recursive: true });

  const pool = getCourseDatabasePool();
  if (!pool) {
    console.error('❌ 无法获取连接池');
    return;
  }

  const client = await pool.connect();
  try {
    // 导出课程
    console.log('📚 导出课程...');
    const coursesResult = await client.query(
      'SELECT payload FROM mentra_courses ORDER BY created_at DESC',
    );
    await fs.writeFile(
      path.join(exportDir, 'courses.json'),
      JSON.stringify(
        coursesResult.rows.map((r) => r.payload),
        null,
        2,
      ),
    );

    // 导出材料提取
    console.log('📄 导出材料提取...');
    const materialsResult = await client.query(
      'SELECT payload FROM mentra_material_extractions ORDER BY created_at DESC',
    );
    await fs.writeFile(
      path.join(exportDir, 'materials.json'),
      JSON.stringify(
        materialsResult.rows.map((r) => r.payload),
        null,
        2,
      ),
    );

    // 导出任务
    console.log('⚙️  导出任务...');
    const jobsResult = await client.query(
      'SELECT payload FROM mentra_artifact_jobs ORDER BY created_at DESC',
    );
    await fs.writeFile(
      path.join(exportDir, 'jobs.json'),
      JSON.stringify(
        jobsResult.rows.map((r) => r.payload),
        null,
        2,
      ),
    );

    // 导出产物
    console.log('🎁 导出产物...');
    const artifactsResult = await client.query(
      'SELECT payload FROM mentra_course_artifacts ORDER BY created_at DESC',
    );
    await fs.writeFile(
      path.join(exportDir, 'artifacts.json'),
      JSON.stringify(
        artifactsResult.rows.map((r) => r.payload),
        null,
        2,
      ),
    );

    console.log(`✅ 导出完成！`);
  } finally {
    client.release();
  }
}

async function generateReport(report: ValidationReport): Promise<void> {
  console.log('\n📊 数据库验证报告');
  console.log('='.repeat(60));

  console.log('\n🔗 连接状态');
  console.log(`  已配置: ${report.database.configured ? '✓' : '✗'}`);
  console.log(`  已连接: ${report.database.connected ? '✓' : '✗'}`);
  if (report.database.database) console.log(`  数据库: ${report.database.database}`);
  if (report.database.error) console.log(`  错误: ${report.database.error}`);

  console.log('\n📈 统计信息');
  console.log(`  课程数: ${report.statistics.courses}`);
  console.log(`  材料数: ${report.statistics.materials}`);
  console.log(`  任务数: ${report.statistics.jobs}`);
  console.log(`  产物数: ${report.statistics.artifacts}`);
  console.log(`  知识包数: ${report.statistics.knowledgePackages}`);

  console.log('\n🔍 数据完整性');
  if (report.integrity.orphanedMaterials.length > 0) {
    console.log(`  ⚠️  孤立材料: ${report.integrity.orphanedMaterials.length}`);
  } else {
    console.log(`  ✓ 孤立材料: 0`);
  }

  if (report.integrity.orphanedJobs.length > 0) {
    console.log(`  ⚠️  孤立任务: ${report.integrity.orphanedJobs.length}`);
  } else {
    console.log(`  ✓ 孤立任务: 0`);
  }

  if (report.integrity.orphanedArtifacts.length > 0) {
    console.log(`  ⚠️  孤立产物: ${report.integrity.orphanedArtifacts.length}`);
  } else {
    console.log(`  ✓ 孤立产物: 0`);
  }

  console.log('\n⚡ 性能指标');
  const indexCount = Object.values(report.performance.indexExists).filter(Boolean).length;
  console.log(`  索引: ${indexCount}/${Object.keys(report.performance.indexExists).length} 存在`);

  const totalSize = Object.values(report.performance.estimatedTableSizes).reduce(
    (a, b) => a + b,
    0,
  );
  console.log(`  总大小: ${(totalSize / 1024 / 1024).toFixed(2)} MB`);

  console.log('\n' + '='.repeat(60));
}

async function main() {
  const args = process.argv.slice(2);
  const exportIndex = args.indexOf('--export');
  const exportDir = exportIndex >= 0 ? args[exportIndex + 1] : undefined;
  const shouldReport = args.includes('--report');

  console.log('🔍 开始课程数据验证...\n');

  const report = await validateDatabase();

  if (shouldReport || !exportDir) {
    await generateReport(report);
  }

  if (exportDir) {
    await exportData(exportDir);
  }

  // 保存完整报告
  const reportPath = path.join(process.cwd(), `validation-report-${Date.now()}.json`);
  await fs.writeFile(reportPath, JSON.stringify(report, null, 2));
  console.log(`\n📋 完整报告已保存: ${reportPath}`);
}

main().catch((error) => {
  console.error('❌ 验证失败:', error);
  process.exit(1);
});
