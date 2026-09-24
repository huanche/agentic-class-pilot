$ErrorActionPreference = 'Stop'
# Standalone acceptance launcher for the teacher agent candidate on :3200 (phase 1).
# Mirrors the proven .runtime/start-teacher-candidate.ps1 from the legacy teacher repo,
# with classroom storage isolation added (CLASSROOMS_DATA_DIR / CLASSROOM_JOBS_DATA_DIR).
$candidate = 'E:\LLM\code_project\ai_education_platform\agent\teacher_agent\SZU-AgentEduPlatform'
# Explicitly isolate the candidate from platform production configuration.
Remove-Item Env:DATABASE_URL,Env:COURSE_DATABASE_URL,Env:PLATFORM_AUTH_ENABLED,Env:ACCESS_CODE -ErrorAction SilentlyContinue
# Standalone profile: JSON storage only, never the shared database.
$env:COURSE_STORAGE_MODE = 'json'
$dataRoot = Join-Path $candidate '.runtime\data-3200'
$env:COURSE_SPACES_DATA_DIR = Join-Path $dataRoot 'course-spaces'
$env:CLASSROOMS_DATA_DIR = Join-Path $dataRoot 'classrooms'
$env:CLASSROOM_JOBS_DATA_DIR = Join-Path $dataRoot 'classroom-jobs'
$env:NEXT_PUBLIC_SAAS_HOST_ORIGIN = 'http://localhost:8080'
$env:ALLOWED_FRAME_ANCESTORS = 'http://localhost:8080'
# Avoid the dev-compile out-of-memory seen during the 3101 acceptance run.
$env:NODE_OPTIONS = '--max-old-space-size=8192'
Set-Location $candidate
# Listen on IPv6 any (::): a dual-stack socket also accepts IPv4-mapped requests.
# Windows resolves `localhost` to ::1 first, so an IPv4-only bind breaks the
# TEACHER_PUBLIC_URL=http://localhost:3200 browser entry.
& .\node_modules\.bin\next.cmd dev --hostname :: --port 3200
