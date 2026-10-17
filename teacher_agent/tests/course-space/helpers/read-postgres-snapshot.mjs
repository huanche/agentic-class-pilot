// A fresh Node process inspects actual PostgreSQL rows, independently of the writer's cache.
import { readFile } from 'node:fs/promises';
import { Client } from 'pg';

const schema = process.env.COURSE_DATABASE_SCHEMA;
if (!/^acceptance_pg_[a-f0-9]+$/.test(schema ?? '')) throw new Error('Invalid acceptance schema');
const client = new Client({
  connectionString: process.env.COURSE_DATABASE_URL,
  options: `-c search_path=${schema}`,
});
try {
  const input = JSON.parse(await readFile(process.argv[2], 'utf8'));
  await client.connect();
  const payload = async (table, id, key = 'id') =>
    (await client.query(`SELECT payload FROM ${table} WHERE ${key}=$1`, [id])).rows[0]?.payload;
  const course = await payload('mentra_courses', input.courseId);
  const bytes = async (key) =>
    (
      await client.query('SELECT bytes FROM mentra_course_material_files WHERE storage_key=$1', [
        key,
      ])
    ).rows[0].bytes.toString('base64');
  process.stdout.write(
    JSON.stringify({
      course,
      artifact: await payload('mentra_course_artifacts', input.artifactId),
      knowledgePackage: await payload('mentra_knowledge_packages', input.packageId),
      extraction: await payload('mentra_material_extractions', input.original.id, 'material_id'),
      originalBytes: await bytes(input.original.storageKey),
      currentBytes: await bytes(course.materials[0].storageKey),
    }),
  );
} finally {
  await client.end();
}
