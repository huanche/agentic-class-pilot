# Validate platform .env before a service launcher starts.
# Usage (from a launcher script):
#   & (Join-Path $suiteRoot 'platform\scripts\validate-platform-env.ps1') `
#       -PlatformEnv $platformEnv -Required @('TEACHER_SERVICE_KEY') `
#       -Recommended @('MINIO_ROOT_PASSWORD')
# Behavior contract:
#   - missing REQUIRED variable  -> throw (launcher cannot start)
#   - missing RECOMMENDED var    -> yellow warning only (fallback exists)
# Required/Recommended lists live in the callers so each service owns its own
# contract; this script only does the checking.
param(
  [Parameter(Mandatory = $true)][string]$PlatformEnv,
  [Parameter(Mandatory = $true)][string[]]$Required,
  [string[]]$Recommended = @()
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $PlatformEnv)) {
  throw "Platform environment file not found: $PlatformEnv"
}
$present = @{}
Get-Content -LiteralPath $PlatformEnv | ForEach-Object {
  if ($_ -match '^([^#=]+)=(.*)$') { $present[$matches[1].Trim()] = $true }
}
$missing = @($Required | Where-Object { -not $present.ContainsKey($_) })
if ($missing.Count -gt 0) {
  $msg = "platform .env 缺少必需变量：" + ($missing -join ', ') + "。请运行 platform/scripts/setup_local.py 重新生成，或参照 platform/.env.example 手工补齐。"
  throw $msg
}
$missingRecommended = @($Recommended | Where-Object { -not $present.ContainsKey($_) })
if ($missingRecommended.Count -gt 0) {
  Write-Warning "platform .env 缺少推荐变量 $($missingRecommended -join ', ')（当前有回落兼容，建议补齐以完成密钥分离）。"
}
Write-Host "platform .env 校验通过（必需 $($Required.Count) 项齐全）。"
