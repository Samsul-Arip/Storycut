$ErrorActionPreference = "Stop"

$appDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$python311 = Join-Path $appDir ".venv311\Scripts\python.exe"
$python = Join-Path $appDir ".venv\Scripts\python.exe"

if (Test-Path -LiteralPath $python311) {
    $python = $python311
}

if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual environment Python was not found. Run setup_python311_env.cmd first."
}

Write-Host "Installing local vision Python packages..."
& $python -m pip install --disable-pip-version-check --timeout 180 --retries 10 -r (Join-Path $appDir "requirements-vision.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install local vision Python packages."
}

Write-Host "Downloading BLIP image captioning model into the local model cache..."
$downloader = @'
import os
import sys

model_name = os.environ.get("STORYCUT_VISION_MODEL", "Salesforce/blip-image-captioning-base")

try:
    from transformers import BlipForConditionalGeneration, BlipProcessor
except Exception as exc:
    print(f"Failed to import transformers BLIP classes: {exc}")
    sys.exit(1)

try:
    BlipProcessor.from_pretrained(model_name)
    BlipForConditionalGeneration.from_pretrained(model_name)
    print(f"Installed local vision model: {model_name}")
except Exception as exc:
    print(f"Failed to download/install BLIP model: {exc}")
    sys.exit(1)
'@

$downloader | & $python -
if ($LASTEXITCODE -ne 0) {
    throw "Failed to download BLIP image captioning model."
}

Write-Host "Vision support installation finished. Restart StoryCut AI before using Auto Describe Empty Notes."
