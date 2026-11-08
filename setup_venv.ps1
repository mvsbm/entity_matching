# Creates .venv with the pinned dependencies on Windows, as setup_venv.sh does on macOS and Linux. In PowerShell:
#   powershell -ExecutionPolicy Bypass -File setup_venv.ps1
# Then .venv\Scripts\nayose --help; in VS Code: Select Kernel -> Python Environments -> .venv (notebooks/demo.ipynb).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$check = "import sys; assert sys.version_info >= (3, 12), 'Python 3.12+ required (PEP 695 generics)'"
$python = @()
if (Get-Command python -ErrorAction SilentlyContinue) {  # the one on PATH; the Store's stub fails the check and is passed over
    python -c $check 2>$null
    if ($LASTEXITCODE -eq 0) { $python = @("python") }
}
if (-not $python -and (Get-Command py -ErrorAction SilentlyContinue)) {  # else the launcher's newest Python 3
    py -3 -c $check 2>$null
    if ($LASTEXITCODE -eq 0) { $python = @("py", "-3") }
}
if (-not $python) {
    Write-Error "Python 3.12 or later not found: install it from python.org (tick 'Add python.exe to PATH'), then run this again"
    exit 1
}
$exe, $rest = $python

& $exe @rest -m venv .venv
if ($LASTEXITCODE) { exit $LASTEXITCODE }
.venv\Scripts\python -m pip install --upgrade pip
if ($LASTEXITCODE) { exit $LASTEXITCODE }
.venv\Scripts\python -m pip install -r requirements.txt
if ($LASTEXITCODE) { exit $LASTEXITCODE }
Write-Host "Done. Run .venv\Scripts\nayose --help; in VS Code: Select Kernel -> Python Environments -> .venv"
