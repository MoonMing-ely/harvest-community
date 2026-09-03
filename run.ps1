$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$VenvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$NeedsInstall = $false
if (-not (Test-Path $VenvPython)) {
    $Python = Get-Command py -ErrorAction SilentlyContinue
    if ($Python) {
        & py -3 -m venv .venv
    } else {
        $Python = Get-Command python -ErrorAction SilentlyContinue
        if (-not $Python) {
            throw "未找到 Python 3.11 或更高版本。请先安装 Python。"
        }
        & python -m venv .venv
    }
    $NeedsInstall = $true
}

if (-not $NeedsInstall) {
    & $VenvPython -c "import harvest" 2>$null
    $NeedsInstall = $LASTEXITCODE -ne 0
}
if ($NeedsInstall) {
    & $VenvPython -m pip install -q -e .
}
& (Join-Path $PSScriptRoot ".venv\Scripts\harvest.exe") @args
exit $LASTEXITCODE
