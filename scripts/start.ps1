# Запуск без Docker в Windows (PowerShell):  powershell -ExecutionPolicy Bypass -File scripts\start.ps1
# Требуется: Python 3.11+, Node.js 20+. Для OCR — Tesseract (https://github.com/UB-Mannheim/tesseract/wiki)
# с языками rus и kaz; путь укажите в .env: TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Test-Path ".venv")) {
    python -m venv .venv
    .\.venv\Scripts\pip install -r backend\requirements-dev.txt
}
if (-not (Test-Path "frontend\dist")) {
    Push-Location frontend
    npm ci
    npm run build
    Pop-Location
}
Write-Host "Открывайте http://localhost:8000 (админ-панель: /admin). Остановка: Ctrl+C"
Set-Location backend
..\.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8000
