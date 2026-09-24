$ErrorActionPreference = 'Stop'

$agentRoot = Split-Path $PSScriptRoot -Parent
$suiteRoot = Split-Path $agentRoot -Parent
$platformEnv = Join-Path $suiteRoot 'platform\.env'
if (-not (Test-Path -LiteralPath $platformEnv)) {
  throw "Platform environment file not found: $platformEnv"
}

Get-Content -LiteralPath $platformEnv | ForEach-Object {
  if ($_ -match '^([^#=]+)=(.*)$') { Set-Item -Path "Env:$($matches[1])" -Value $matches[2] }
}
$studentEnv = Join-Path $agentRoot '.env.local'
if (Test-Path -LiteralPath $studentEnv) {
  Get-Content -LiteralPath $studentEnv | ForEach-Object {
    if ($_ -match '^([^#=]+)=(.*)$') {
      Set-Item -Path "Env:$($matches[1])" -Value $matches[2].Trim('"')
    }
  }
}
if (-not $env:STUDENT_SERVICE_KEY) { throw 'STUDENT_SERVICE_KEY is missing from platform .env' }

$env:PLATFORM_AUTH_URL = 'http://127.0.0.1:8080/api/v1'
$env:STUDENT_DEMO_MODE = 'false'
Set-Location $agentRoot
& .\.venv\Scripts\python.exe apps\start.py --no-browser --host 127.0.0.1 --port 8000
