$ErrorActionPreference = "Stop"

$appDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $appDir ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual environment Python was not found: $python"
}

Write-Host "Installing Python OCR packages..."
& $python -m pip install --disable-pip-version-check --timeout 120 --retries 10 -r (Join-Path $appDir "requirements-ocr.txt")

$tesseract = Get-Command tesseract -ErrorAction SilentlyContinue
$defaultTesseract = "C:\Program Files\Tesseract-OCR\tesseract.exe"

if ($tesseract -or (Test-Path -LiteralPath $defaultTesseract)) {
    Write-Host "Tesseract OCR is already installed."
    exit 0
}

Write-Host "Installing Tesseract OCR with winget..."
winget install -e --id UB-Mannheim.TesseractOCR --accept-source-agreements --accept-package-agreements

Write-Host "OCR support installation finished. Restart StoryCut AI before using OCR."
