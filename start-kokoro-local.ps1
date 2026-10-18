[CmdletBinding()]
param(
  [ValidateRange(1024, 65535)][int]$Port = 13305,
  [ValidateRange(1, 16)][int]$Threads = 4
)

$ErrorActionPreference = 'Stop'
$runtime = Join-Path $PSScriptRoot 'teacher_agent\.runtime\kokoro'
$source = Join-Path $PSScriptRoot 'teacher_agent\devtools\kokoro-local'
foreach ($folder in @('tmp', 'cache\pip', 'cache\huggingface', 'models', 'samples')) {
  New-Item -ItemType Directory -Path (Join-Path $runtime $folder) -Force | Out-Null
}
$env:PYTHONUTF8 = '1'
$env:PYTHONUNBUFFERED = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PIP_CACHE_DIR = Join-Path $runtime 'cache\pip'
$env:HF_HOME = Join-Path $runtime 'cache\huggingface'
$env:TEMP = Join-Path $runtime 'tmp'
$env:TMP = $env:TEMP
$python = Join-Path $runtime 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
  $basePython = (Get-Command python.exe -ErrorAction Stop).Source
  & $basePython -m venv (Join-Path $runtime 'venv')
  if ($LASTEXITCODE -ne 0) { throw 'Creating the project-local Python environment failed.' }
}
$requirements = Join-Path $source 'requirements.txt'
$stamp = Join-Path $runtime 'installed-requirements.sha256'
$requirementsHash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash
if (-not (Test-Path -LiteralPath $stamp) -or (Get-Content -LiteralPath $stamp -Raw).Trim() -ne $requirementsHash) {
  & $python -m pip install --disable-pip-version-check -r $requirements
  if ($LASTEXITCODE -ne 0) { throw 'Installing Kokoro dependencies failed.' }
  Set-Content -LiteralPath $stamp -Value $requirementsHash -Encoding ascii
}
& $python (Join-Path $source 'download_models.py') --root $runtime
if ($LASTEXITCODE -ne 0) { throw 'Downloading Kokoro models failed.' }
Write-Host "Kokoro local listening page: http://127.0.0.1:$Port"
& $python (Join-Path $source 'server.py') --root $runtime --port $Port --threads $Threads
exit $LASTEXITCODE
