#!/usr/bin/env bash
# Best-effort drain of recent server generation jobs before replacing the teacher.
set -euo pipefail
if ! docker container inspect agentic-teacher-prod >/dev/null 2>&1; then exit 0; fi
for attempt in $(seq 1 60); do
  active="$(docker exec -i agentic-teacher-prod node - <<'JS'
const fs = require('node:fs/promises');
const path = require('node:path');
(async () => {
  const since = Date.now() - 30 * 60 * 1000;
  let active = 0;
  const database = process.env.COURSE_DATABASE_URL || process.env.DATABASE_URL;
  if (database && process.env.COURSE_STORAGE_MODE !== 'json') {
    const { Pool } = require('pg');
    const pool = new Pool({ connectionString: database, connectionTimeoutMillis: 5000 });
    try {
      const result = await pool.query(
        "SELECT count(*)::int AS count FROM mentra_artifact_jobs WHERE status IN ('queued','running') AND updated_at > $1", [since]);
      active += result.rows[0].count;
    } catch (error) {
      if (error.code !== '42P01') throw error;
    } finally { await pool.end(); }
  }
  const directories = [process.env.CLASSROOM_JOBS_DATA_DIR || '/app/data/classroom-jobs'];
  if (!database || process.env.COURSE_STORAGE_MODE === 'json')
    directories.push(path.join(process.env.COURSE_SPACES_DATA_DIR || '/app/data/course-spaces', 'jobs'));
  for (const directory of directories) {
    let files;
    try { files = await fs.readdir(directory); } catch (error) { if(error.code==='ENOENT') continue; throw error; }
    for (const name of files.filter(name=>name.endsWith('.json'))) {
      let job;
      try { job = JSON.parse(await fs.readFile(path.join(directory,name),'utf8')); }
      catch (error) { if(error.code==='ENOENT') continue; throw error; }
      const updated = typeof job.updatedAt === 'number' ? job.updatedAt : Date.parse(job.updatedAt);
      if (['queued','running'].includes(job.status) && updated > since) active++;
    }
  }
  console.log(active);
})().catch(()=>{ console.error('Could not check active teacher generation jobs.'); process.exit(1); });
JS
  )"
  [[ "$active" =~ ^[0-9]+$ ]] || { echo 'Invalid generation count; keeping the current teacher.'; exit 1; }
  if [ "$active" = 0 ]; then echo 'No recent active teacher generation jobs.'; exit 0; fi
  echo "Waiting for $active generation jobs before deployment ($attempt/60)."
  sleep 10
done
echo 'Generation jobs are still active; the running teacher has not been replaced.'
exit 1
