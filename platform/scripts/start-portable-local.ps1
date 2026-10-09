[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$platformRoot = Split-Path $PSScriptRoot -Parent
$projectRoot = Split-Path $platformRoot -Parent
$runtimeRoot = Join-Path $platformRoot '.runtime'
$asciiRuntime = Join-Path $env:TEMP 'agentedu-pilot-14-runtime'
if (-not (Test-Path -LiteralPath $asciiRuntime)) {
  New-Item -ItemType Junction -Path $asciiRuntime -Target $runtimeRoot | Out-Null
}
Get-Content -LiteralPath (Join-Path $platformRoot '.env') | ForEach-Object {
  if ($_ -match '^([^#=]+)=(.*)$') { Set-Item -Path "Env:$($matches[1])" -Value $matches[2] }
}
function Has-Port([int]$Port) { return [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) }
$pgCtl=Join-Path $asciiRuntime 'postgresql/pgsql/bin/pg_ctl.exe'
if (-not (Has-Port 55432)) {
  & $pgCtl -D (Join-Path $asciiRuntime 'pgdata') -l (Join-Path $asciiRuntime 'postgresql.log') -o '-h 127.0.0.1 -p 55432' -w start
  if ($LASTEXITCODE -ne 0) { throw 'Local PostgreSQL failed to start' }
}
$started=@()
if (-not (Has-Port 8080)) {
  $started += Start-Process -FilePath (Join-Path $platformRoot '.venv/Scripts/python.exe') -ArgumentList '-m uvicorn app.main:app --host 127.0.0.1 --port 8080' -WorkingDirectory (Join-Path $platformRoot 'backend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeRoot 'platform.stdout.log') -RedirectStandardError (Join-Path $runtimeRoot 'platform.stderr.log') -PassThru
}
if (-not (Has-Port 3200)) {
  $teacherRoot=Join-Path $projectRoot 'teacher_agent'
  $teacherLauncher=Join-Path $teacherRoot 'scripts/dev-3200-platform.ps1'
  $started += Start-Process -FilePath 'powershell.exe' -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$teacherLauncher`"" -WorkingDirectory $teacherRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeRoot 'teacher.stdout.log') -RedirectStandardError (Join-Path $runtimeRoot 'teacher.stderr.log') -PassThru
}
if (-not (Has-Port 8000)) {
  $studentRoot=Join-Path $projectRoot 'student_agent'
  $studentLauncher=Join-Path $studentRoot 'scripts/dev-8000-platform.ps1'
  $started += Start-Process -FilePath 'powershell.exe' -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$studentLauncher`"" -WorkingDirectory $studentRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeRoot 'student.stdout.log') -RedirectStandardError (Join-Path $runtimeRoot 'student.stderr.log') -PassThru
}
if (-not (Has-Port 8088)) {
  $gateway=Join-Path $PSScriptRoot 'local-gateway.mjs'
  $started += Start-Process -FilePath (Get-Command node.exe).Source -ArgumentList "`"$gateway`"" -WorkingDirectory $platformRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeRoot 'gateway.stdout.log') -RedirectStandardError (Join-Path $runtimeRoot 'gateway.stderr.log') -PassThru
}
$started | Select-Object Id,ProcessName | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtimeRoot 'local-processes.json') -Encoding utf8
Write-Output 'Local services starting at http://localhost:8088. Credentials: platform/LOCAL-ACCESS.txt'
