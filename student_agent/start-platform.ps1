$ErrorActionPreference = 'Stop'

$studentRoot = $PSScriptRoot
$suiteRoot = Split-Path $studentRoot -Parent
$platformRoot = Join-Path $suiteRoot 'platform'
$platformEnv = Join-Path $platformRoot '.env'
if (-not (Test-Path -LiteralPath $platformEnv)) {
  throw "Platform environment file not found: $platformEnv"
}

Get-Content -LiteralPath $platformEnv | ForEach-Object {
  if ($_ -match '^([^#=]+)=(.*)$') {
    Set-Item -Path "Env:$($matches[1])" -Value $matches[2].Trim('"')
  }
}
if (-not $env:STUDENT_SERVICE_KEY) { throw 'STUDENT_SERVICE_KEY is missing from platform .env' }
$env:PLATFORM_AUTH_URL = "$($env:PLATFORM_URL.TrimEnd('/'))/api/v1"
# Browser snapshots identify a lesson for database recovery; a lesson without
# a local snapshot also recovers its database session after platform validation.
$env:STUDENT_FRESH_SESSION_MODE = '1'
Remove-Item Env:STUDENT_NEW_DEMO_PLAYER_URL -ErrorAction SilentlyContinue

# Optional local model configuration stays with this student service.
$studentEnv = Join-Path $studentRoot '.env.local'
if (Test-Path -LiteralPath $studentEnv) {
  $modelConfig = @{}
  Get-Content -LiteralPath $studentEnv | ForEach-Object {
    if ($_ -match '^([^#=]+)=(.*)$') { $modelConfig[$matches[1]] = $matches[2].Trim('"') }
  }
  if (-not $env:STUDENT_AGENT_API_KEY -and $modelConfig['AGENT_LLM_API_KEY']) {
    $env:STUDENT_AGENT_API_KEY = $modelConfig['AGENT_LLM_API_KEY']
    $env:STUDENT_AGENT_BASE_URL = $modelConfig['AGENT_LLM_BASE_URL']
    $env:STUDENT_AGENT_MODEL = $modelConfig['AGENT_LLM_MODEL']
  }
}

$python = Join-Path $platformRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = 'python' }
Push-Location $studentRoot
try {
  & $python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
} finally {
  Pop-Location
}
