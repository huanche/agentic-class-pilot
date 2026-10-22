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
if (-not $env:STUDENT_DATABASE_URL -and $env:STUDENT_DB_PASSWORD) {
    $studentDbPassword = [uri]::EscapeDataString($env:STUDENT_DB_PASSWORD)
    $env:STUDENT_DATABASE_URL = "postgresql://student:${studentDbPassword}@127.0.0.1:55432/education"
}
& (Join-Path $suiteRoot 'platform\scripts\validate-platform-env.ps1') -PlatformEnv $platformEnv `
  -Required @('STUDENT_SERVICE_KEY') `
  -Recommended @('STUDENT_DATABASE_URL', 'STUDENT_TOKEN_SIGNING_KEY')

$env:PLATFORM_AUTH_URL = 'http://127.0.0.1:8080/api/v1'
$env:STUDENT_DEMO_MODE = 'false'
# 本地测试（工单 07）：视频页显示「当作已播完」按钮——教师端播放器不方便
# 常开时，学生端全链路（视频完→课后辅导）依然可以完整走通。生产不设此变量。
$env:AGENT_ALLOW_VIDEO_SKIP = 'true'
Set-Location $agentRoot
& .\.venv\Scripts\python.exe apps\start.py --no-browser --host 127.0.0.1 --port 8000
