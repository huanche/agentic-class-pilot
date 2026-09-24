$ErrorActionPreference = 'Stop'
# Phase-2 launcher: the teacher agent candidate on :3200 WITH platform identity
# delegation enabled. Mirrors scripts/dev-3200.ps1 (isolated data directories);
# the shared service key is read from the platform .env at runtime, never committed.
$candidate = Split-Path $PSScriptRoot -Parent
$suiteRoot = Split-Path $candidate -Parent
$platformEnv = Join-Path $suiteRoot 'platform\.env'
Get-Content -LiteralPath $platformEnv | ForEach-Object {
  if ($_ -match '^([^#=]+)=(.*)$') { Set-Item -Path "Env:$($matches[1])" -Value $matches[2] }
}
# Phase 3: the platform-auth profile runs on the shared PostgreSQL (teacher schema,
# DML only — migrations own the DDL). No silent JSON fallback in this mode.
$env:COURSE_STORAGE_MODE = 'postgres'
$env:COURSE_DATABASE_SCHEMA = 'teacher'
$env:COURSE_DATABASE_URL = "postgresql://teacher:$($env:TEACHER_DB_PASSWORD)@127.0.0.1:55432/education"
if (-not $env:TEACHER_DB_PASSWORD) { throw 'TEACHER_DB_PASSWORD missing from platform .env' }
Remove-Item Env:DATABASE_URL,Env:ACCESS_CODE -ErrorAction SilentlyContinue
$dataRoot = Join-Path $candidate '.runtime\data-3200'
$env:COURSE_SPACES_DATA_DIR = Join-Path $dataRoot 'course-spaces'
$env:CLASSROOMS_DATA_DIR = Join-Path $dataRoot 'classrooms'
$env:CLASSROOM_JOBS_DATA_DIR = Join-Path $dataRoot 'classroom-jobs'
$env:PLATFORM_AUTH_ENABLED = 'true'
$env:PLATFORM_AUTH_URL = 'http://127.0.0.1:8080'
$env:PLATFORM_PUBLIC_URL = 'http://localhost:8088'
$env:PLATFORM_SERVICE_KEY = $env:TEACHER_SERVICE_KEY
if (-not $env:PLATFORM_SERVICE_KEY) { throw 'TEACHER_SERVICE_KEY missing from platform .env' }
$env:COURSE_OBJECT_STORAGE_SECRET_KEY = $env:TEACHER_DB_PASSWORD
$env:NEXT_PUBLIC_SAAS_HOST_ORIGIN = 'http://localhost:8088'
$env:ALLOWED_FRAME_ANCESTORS = 'http://localhost:8088'
$env:NODE_OPTIONS = '--max-old-space-size=8192'
Set-Location $candidate
# Listen on IPv6 any (::): a dual-stack socket also accepts IPv4-mapped requests.
# Windows resolves `localhost` to ::1 first, so an IPv4-only bind breaks the
# TEACHER_PUBLIC_URL=http://localhost:3200 browser entry.
& .\node_modules\.bin\next.cmd dev --hostname :: --port 3200
