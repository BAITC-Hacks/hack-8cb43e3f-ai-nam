$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv-ainam/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    Write-Host 'Preparing the Python environment...'
    python -m venv .venv-ainam
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 or newer and try again.' }
    & $pythonPath -m pip install -r requirements.lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check the connection and try again.' }
}
Write-Host 'AI-NAM: http://127.0.0.1:8765 (Ctrl+C to stop)'
& $pythonPath run.py
