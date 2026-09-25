$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

function Test-LocalPort([int]$port) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $result = $client.BeginConnect('127.0.0.1', $port, $null, $null)
        if (-not $result.AsyncWaitHandle.WaitOne(150)) { return $false }
        $client.EndConnect($result)
        return $true
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Get-ExistingDemoUrl {
    foreach ($candidatePort in 3000..3010) {
        if (-not (Test-LocalPort $candidatePort)) { continue }
        $candidateUrl = "http://127.0.0.1:$candidatePort"
        try {
            $response = Invoke-WebRequest -Uri $candidateUrl -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -eq 200 -and $response.Content -match 'AI 学习空间 · 学生端') {
                return $candidateUrl
            }
        } catch { }
    }
    return $null
}

try {
    $node = Get-Command node -ErrorAction Stop
    $npm = Get-Command npm.cmd -ErrorAction Stop
} catch {
    Write-Host '未找到 Node.js 或 npm。请先安装 Node.js 20.9+，然后重新双击启动演示.cmd。' -ForegroundColor Red
    exit 1
}

$nodeVersion = (& $node.Source --version).TrimStart('v')
if ([version]$nodeVersion -lt [version]'20.9.0') {
    Write-Host "Node.js 版本过低（当前 $nodeVersion），需要 20.9 或更高版本。" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'node_modules/next/package.json'))) {
    Write-Host '首次启动：正在安装项目依赖（npm ci）...'
    & $npm.Source ci
    if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请检查网络连接和 npm 配置。' }
}

$existingUrl = Get-ExistingDemoUrl
if ($existingUrl) {
    Write-Host "检测到已运行的演示服务：$existingUrl" -ForegroundColor Green
    Start-Process $existingUrl
    exit 0
}

$port = 3000..3010 | Where-Object { -not (Test-LocalPort $_) } | Select-Object -First 1
if ($null -eq $port) { throw '3000–3010 端口均被占用，请关闭占用端口的程序后重试。' }

$url = "http://127.0.0.1:$port"
$nextCli = Join-Path $projectRoot 'node_modules/next/dist/bin/next'
Write-Host "正在启动演示：$url"

$server = $null
try {
    $server = Start-Process -FilePath $node.Source -ArgumentList @($nextCli, 'dev', '--hostname', '127.0.0.1', '--port', [string]$port) -PassThru -NoNewWindow
    $ready = $false
    $timer = [Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt 90) {
        Start-Sleep -Milliseconds 250
        if ($server.HasExited) { throw '前端服务意外退出，请查看上方错误信息。' }
        try {
            $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) { $ready = $true; break }
        } catch { }
    }
    if (-not $ready) { throw '等待前端服务就绪超时，请查看上方错误信息。' }

    Start-Process $url
    Write-Host "演示已就绪：$url" -ForegroundColor Green
    Write-Host '保持此窗口打开；演示结束后按回车停止服务。'
    [void](Read-Host)
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
} finally {
    if ($server -and -not $server.HasExited) {
        & taskkill.exe /PID $server.Id /T /F | Out-Null
        Write-Host '演示服务已停止。'
    }
}
