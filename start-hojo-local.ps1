[CmdletBinding()]
param(
  [ValidateRange(1024, 65535)][int]$Port = 13306,
  [ValidateRange(1, 32)][int]$Threads = 4,
  [ValidateSet('40m', '80m', 'both')][string]$Models = '40m'
)
$ErrorActionPreference = 'Stop'
$hojoRoot = Join-Path $PSScriptRoot 'teacher_agent\.runtime\hojo-local'
$hojoSource = Join-Path $PSScriptRoot 'teacher_agent\devtools\hojo-local'
New-Item -ItemType Directory -Path $hojoRoot -Force | Out-Null
$hojoPython = Join-Path $hojoRoot 'venv\Scripts\python.exe'
$env:PYTHONUTF8 = '1'
$env:PYTHONUNBUFFERED = '1'
if (-not (Test-Path -LiteralPath $hojoPython)) {
  & python -m venv (Join-Path $hojoRoot 'venv')
  if ($LASTEXITCODE -ne 0) { throw '创建 Hojo Python 环境失败' }
}
$hojoRequirements = Join-Path $hojoSource 'requirements.txt'
$hojoStamp = Join-Path $hojoRoot 'installed-requirements.sha256'
$hojoHash = (Get-FileHash -LiteralPath $hojoRequirements -Algorithm SHA256).Hash
if (-not (Test-Path -LiteralPath $hojoStamp) -or (Get-Content -LiteralPath $hojoStamp -Raw).Trim() -ne $hojoHash) {
  & $hojoPython -m pip install --disable-pip-version-check -r $hojoRequirements
  if ($LASTEXITCODE -ne 0) { throw '安装 Hojo 依赖失败' }
  Set-Content -LiteralPath $hojoStamp -Value $hojoHash -Encoding ascii
}
$hojoSizes = if ($Models -eq 'both') { @('40m', '80m') } else { @($Models) }
& $hojoPython (Join-Path $hojoSource 'download_models.py') --root $hojoRoot --models @hojoSizes
if ($LASTEXITCODE -ne 0) { throw '下载 Hojo 模型失败' }
& $hojoPython (Join-Path $hojoSource 'server.py') --root $hojoRoot --port $Port --threads $Threads
exit $LASTEXITCODE
