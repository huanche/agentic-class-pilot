$ErrorActionPreference = 'Stop'

$platformRoot = Split-Path -Parent $PSScriptRoot
Set-Location $platformRoot

docker compose -f compose.local.yml up -d gateway
if ($LASTEXITCODE -ne 0) { throw 'Failed to start the unified gateway.' }

Write-Host 'Unified local entry: http://localhost:8088'
Write-Host 'Teacher entry:       http://localhost:8088/teacher/teacher-workspace'
Write-Host 'Student entry:       http://localhost:8088/app'
