$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

function Invoke-Checked([string]$FilePath, [string[]]$Arguments) {
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath failed with exit code $LASTEXITCODE"
    }
}

try {
    $preferredPython = Join-Path $env:USERPROFILE '.workbuddy\binaries\python\envs\default\Scripts\python.exe'
    if (Test-Path -LiteralPath $preferredPython) {
        $python = $preferredPython
    } else {
        $python = (Get-Command python -ErrorAction Stop).Source
    }

    & $python -c 'import fastapi, uvicorn, langgraph' 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host '[1/3] Installing backend dependencies...' -ForegroundColor Cyan
        Invoke-Checked $python @('-m', 'pip', 'install', '-r', 'requirements.txt')
    } else {
        Write-Host '[1/3] Backend dependencies are ready.' -ForegroundColor Green
    }

    $frontendOutput = Join-Path $projectRoot 'frontend\out\index.html'
    $node = Get-Command node -ErrorAction SilentlyContinue
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($node -and $npm) {
        $nodeVersion = (& $node.Source --version).TrimStart('v')
        if ([version]$nodeVersion -lt [version]'20.9.0') {
            throw "Node.js $nodeVersion is too old. Version 20.9 or newer is required."
        }
        Write-Host '[2/3] Building the student frontend...' -ForegroundColor Cyan
        if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'frontend\node_modules\next\package.json'))) {
            Invoke-Checked $npm.Source @('ci', '--prefix', 'frontend')
        }
        Invoke-Checked $npm.Source @('run', 'build', '--prefix', 'frontend')
    } elseif (-not (Test-Path -LiteralPath $frontendOutput)) {
        throw 'Node.js/npm was not found and no frontend build exists. Install Node.js 20.9 or newer.'
    } else {
        Write-Host '[2/3] npm was not found; using the existing frontend build.' -ForegroundColor Yellow
    }

    Write-Host '[3/3] Starting the classroom service...' -ForegroundColor Cyan
    & $python 'apps\start.py' @args
    if ($LASTEXITCODE -ne 0) {
        throw "The classroom service exited with code $LASTEXITCODE"
    }
} catch {
    Write-Host ''
    Write-Host ('Startup failed: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host 'This window will remain open so you can read the error.' -ForegroundColor Yellow
    [void](Read-Host 'Press Enter to close')
    exit 1
}
