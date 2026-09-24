<#
Starts the local platform, PostgreSQL, and the independent teacher service.
Run this script from PowerShell after the one-time bootstrap script.
#>
[CmdletBinding()]
param(
  [string]$TeacherProject,
  [string]$StudentProject
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
if (-not $TeacherProject) {
  $projectRoot = Split-Path $root -Parent
  $TeacherProject = Join-Path $projectRoot 'teacher_agent'
}
if (-not $StudentProject) {
  $projectRoot = Split-Path $root -Parent
  $StudentProject = Join-Path $projectRoot 'student_agent'
}
$envFile = Join-Path $root '.env'
if (-not (Test-Path -LiteralPath $envFile)) {
  throw "Missing $envFile. Run scripts\setup_local.py first."
}

Get-Content -LiteralPath $envFile | ForEach-Object {
  if ($_ -match '^([^#=]+)=(.*)$') { Set-Item -Path "Env:$($matches[1])" -Value $matches[2] }
}

function Test-Port([int]$Port) {
  return [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

Push-Location $root
try {
  docker compose -f compose.local.yml up -d
  if ($LASTEXITCODE -ne 0) {
    throw 'Docker services failed to start. Make sure Docker Desktop is running and this terminal can access it.'
  }
  Push-Location (Join-Path $root 'backend')
  try { & (Join-Path $root '.venv\Scripts\python.exe') -m alembic upgrade head } finally { Pop-Location }
  if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }

  if (-not (Test-Path -LiteralPath (Join-Path $root 'backend\app\frontend\index.html'))) {
    Push-Location (Join-Path $root 'frontend')
    try { & (Join-Path $root 'node_modules\.bin\vite.exe') build } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
  }

  if (-not (Test-Port 8080)) {
    Start-Process -FilePath (Join-Path $root '.venv\Scripts\python.exe') -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8080') -WorkingDirectory (Join-Path $root 'backend') -WindowStyle Hidden
  }

  if (-not (Test-Path -LiteralPath $TeacherProject)) { throw "Teacher project not found: $TeacherProject" }
  if (-not (Test-Port 3200)) {
    $teacherLauncher = Join-Path $TeacherProject 'scripts\dev-3200-platform.ps1'
    if (-not (Test-Path -LiteralPath $teacherLauncher)) {
      throw "Teacher launcher not found: $teacherLauncher"
    }
    $teacherArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$teacherLauncher`""
    Start-Process -FilePath 'powershell.exe' -ArgumentList $teacherArgs -WorkingDirectory $TeacherProject -WindowStyle Hidden
  }

  if (-not (Test-Path -LiteralPath $StudentProject)) { throw "Student project not found: $StudentProject" }
  if (-not (Test-Port 8000)) {
    $studentLauncher = Join-Path $StudentProject 'scripts\dev-8000-platform.ps1'
    if (-not (Test-Path -LiteralPath $studentLauncher)) {
      throw "Student launcher not found: $studentLauncher"
    }
    $studentArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$studentLauncher`""
    Start-Process -FilePath 'powershell.exe' -ArgumentList $studentArgs -WorkingDirectory $StudentProject -WindowStyle Hidden
  }
} finally {
  Pop-Location
}

Write-Host 'Platform is starting. Open http://localhost:8088 after a few seconds.'
