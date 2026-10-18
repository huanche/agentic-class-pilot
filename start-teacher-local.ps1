[CmdletBinding()]
param(
  [ValidateRange(1024, 65535)]
  [int]$Port = 3200
)

$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'teacher_agent\scripts\dev-3200.ps1') -Port $Port
exit $LASTEXITCODE
