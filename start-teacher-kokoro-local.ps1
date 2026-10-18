[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$runtime = Join-Path $PSScriptRoot 'teacher_agent\.runtime\kokoro'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
$localReady = $false
try {
  $health = Invoke-RestMethod -Uri 'http://127.0.0.1:13305/health' -TimeoutSec 2
  $localReady = $health.engine -eq 'kokoro-onnx' -and $health.status -eq 'ready'
} catch {}
if (-not $localReady) {
  if (Get-NetTCPConnection -LocalPort 13305 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Port 13305 is occupied by another service; close that service or choose another TTS port.'
  }
  $launcher = Join-Path $PSScriptRoot 'start-kokoro-local.ps1'
  $shell = (Get-Process -Id $PID).Path
  $child = Start-Process -FilePath $shell -ArgumentList @('-NoProfile', '-File', ('"' + $launcher + '"')) -WindowStyle Hidden -WorkingDirectory $PSScriptRoot -RedirectStandardOutput (Join-Path $runtime 'stdout.log') -RedirectStandardError (Join-Path $runtime 'stderr.log') -PassThru
  Set-Content -LiteralPath (Join-Path $runtime 'launcher.pid') -Value $child.Id -Encoding ascii
  Write-Host 'Starting local Kokoro. The first setup downloads dependencies and model weights.'
  # First installation can take several minutes; logs remain in the project.
  $deadline = (Get-Date).AddMinutes(20)
  while ((Get-Date) -lt $deadline) {
    if ($child.HasExited) { throw "Kokoro exited; see $runtime\stderr.log" }
    try {
      $health = Invoke-RestMethod -Uri 'http://127.0.0.1:13305/health' -TimeoutSec 2
      if ($health.engine -eq 'kokoro-onnx' -and $health.status -eq 'ready') { $localReady = $true; break }
    } catch {}
    Start-Sleep -Seconds 2
  }
  if (-not $localReady) { throw "Kokoro startup timed out; see $runtime\stdout.log" }
}
$python = Join-Path $runtime 'venv\Scripts\python.exe'
& $python (Join-Path $PSScriptRoot 'teacher_agent\devtools\kokoro-local\configure_teacher.py')
if ($LASTEXITCODE -ne 0) { throw 'Configuring local teacher TTS failed.' }
Write-Host 'Listen: http://127.0.0.1:13305/'
Write-Host 'Teacher: http://127.0.0.1:3200/course-space'
if (Get-NetTCPConnection -LocalPort 3200 -State Listen -ErrorAction SilentlyContinue) {
  Write-Host 'Port 3200 is already listening. Keep the existing teacher process and refresh the page.'
  return
}
& (Join-Path $PSScriptRoot 'start-teacher-local.ps1')
