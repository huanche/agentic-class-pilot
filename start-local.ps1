[CmdletBinding()]
param(
  [switch]$CheckOnly,
  [switch]$SkipInfrastructure,
  [switch]$SkipBuild,
  [switch]$Stop
)

$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot 'platform\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
  throw 'Platform Python environment is missing. Follow README first-time installation instructions.'
}
$launcherArgs = @((Join-Path $PSScriptRoot 'scripts\local_dev.py'))
if ($CheckOnly) { $launcherArgs += '--check' }
if ($SkipInfrastructure) { $launcherArgs += '--skip-infrastructure' }
if ($SkipBuild) { $launcherArgs += '--skip-build' }
if ($Stop) { $launcherArgs += '--stop' }
& $python @launcherArgs
exit $LASTEXITCODE
