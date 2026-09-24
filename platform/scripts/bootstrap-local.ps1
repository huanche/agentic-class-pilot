<# Installs local Python and frontend dependencies once. #>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Push-Location $root
try {
  uv sync --frozen --package app
  npx --yes bun@1.3.11 install --frozen-lockfile
  if (-not (Test-Path -LiteralPath (Join-Path $root '.env'))) {
    & (Join-Path $root '.venv\Scripts\python.exe') scripts\setup_local.py
  }
} finally {
  Pop-Location
}

Write-Host 'Bootstrap complete. Run scripts\start-local.ps1.'
