$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$VenvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$RuntimeLock = Join-Path $PSScriptRoot "requirements\runtime.lock"
$LockSnapshot = Join-Path $PSScriptRoot ".venv\.harvest-runtime.lock"
$NeedsInstall = (-not (Test-Path $VenvPython))
if (-not $NeedsInstall) {
    $NeedsInstall = (-not (Test-Path $LockSnapshot))
}
if (-not $NeedsInstall) {
    $NeedsInstall = (Get-FileHash $RuntimeLock).Hash -ne (Get-FileHash $LockSnapshot).Hash
}

if ($NeedsInstall) {
    $Python = Get-Command py -ErrorAction SilentlyContinue
    if ($Python) {
        $PythonExe = "py"
        $PythonArgs = @("-3")
    } else {
        $Python = Get-Command python -ErrorAction SilentlyContinue
        if (-not $Python) {
            throw "未找到 Python 3.11 或更高版本。请先安装 Python。"
        }
        $PythonExe = "python"
        $PythonArgs = @()
    }
    & $PythonExe @PythonArgs -c "import sys; raise SystemExit(sys.version_info < (3, 11))"
    if ($LASTEXITCODE -ne 0) {
        throw "Python 版本低于 3.11。请先升级 Python。"
    }
    $VenvPath = Join-Path $PSScriptRoot ".venv"
    if (Test-Path $VenvPath) {
        Remove-Item -Recurse -Force $VenvPath
    }
    & $PythonExe @PythonArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        throw "无法创建 Python 虚拟环境。"
    }
    & $VenvPython -m pip install -q --require-hashes -r $RuntimeLock
    if ($LASTEXITCODE -ne 0) {
        throw "依赖安装失败；虚拟环境未标记为可用。"
    }
    Copy-Item $RuntimeLock $LockSnapshot
}
$env:PYTHONPATH = Join-Path $PSScriptRoot "src"
& $VenvPython -m harvest @args
exit $LASTEXITCODE
