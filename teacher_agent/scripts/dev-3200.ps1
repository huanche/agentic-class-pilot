[CmdletBinding()]
param(
  [ValidateRange(1024, 65535)]
  [int]$Port = 3200
)

$ErrorActionPreference = 'Stop'
# Resolve all application paths from this checkout, including after moving it.
$candidate = Split-Path $PSScriptRoot -Parent
$node = (Get-Command node.exe -ErrorAction Stop).Source
$next = Join-Path $candidate 'node_modules\next\dist\bin\next'
if (-not (Test-Path -LiteralPath $next)) {
  throw 'Teacher dependencies are missing. Install them in teacher_agent first.'
}
# Explicitly isolate the candidate from platform production configuration.
Remove-Item Env:DATABASE_URL,Env:COURSE_DATABASE_URL,Env:PLATFORM_AUTH_ENABLED,Env:ACCESS_CODE -ErrorAction SilentlyContinue
# Standalone profile: JSON storage only, never the shared database.
$env:COURSE_STORAGE_MODE = 'json'
$env:PLATFORM_AUTH_ENABLED = 'false'
$dataRoot = Join-Path $candidate ".runtime\data-$Port"
New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null
$env:COURSE_SPACES_DATA_DIR = Join-Path $dataRoot 'course-spaces'
$env:CLASSROOMS_DATA_DIR = Join-Path $dataRoot 'classrooms'
$env:CLASSROOM_JOBS_DATA_DIR = Join-Path $dataRoot 'classroom-jobs'
$env:NEXT_PUBLIC_SAAS_HOST_ORIGIN = "http://127.0.0.1:$Port"
$env:ALLOWED_FRAME_ANCESTORS = "http://127.0.0.1:$Port http://localhost:$Port"
# Avoid the dev-compile out-of-memory seen during the 3101 acceptance run.
$env:NODE_OPTIONS = '--max-old-space-size=8192'
Push-Location $candidate
try {
  Write-Host "Teacher development server: http://127.0.0.1:$Port"
  Write-Host "Local classroom data: $dataRoot"
  # Loopback-only standalone development; Next loads this project's .env.local.
  & $node $next dev --hostname 127.0.0.1 --port $Port
  $serverExitCode = $LASTEXITCODE
} finally {
  Pop-Location
}
exit $serverExitCode
