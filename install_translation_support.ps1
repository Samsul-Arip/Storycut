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

$versionInfo = & $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ([version]$versionInfo -ge [version]"3.13") {
    Write-Host "Translation support is not compatible with Python $versionInfo on Windows because sentencepiece has no stable wheel."
    Write-Host "Creating a Python 3.11 environment first..."
    powershell -ExecutionPolicy Bypass -File (Join-Path $appDir "setup_python311_env.ps1")
    $python = $python311
    if (-not (Test-Path -LiteralPath $python)) {
        throw "Python 3.11 environment was not created. Double-click setup_python311_env.cmd, then run this installer again."
    }
}

Write-Host "Installing Argos Translate Python package..."
& $python -m pip install --disable-pip-version-check --timeout 120 --retries 10 -r (Join-Path $appDir "requirements-translation.txt")

Write-Host "Downloading and installing English -> Indonesian offline translation model..."
$installer = @'
import sys

try:
    import argostranslate.package
    import argostranslate.translate
except Exception as exc:
    print(f"Failed to import Argos Translate: {exc}")
    sys.exit(1)

try:
    argostranslate.package.update_package_index()
    available_packages = argostranslate.package.get_available_packages()
    package = next(
        (
            package
            for package in available_packages
            if package.from_code == "en" and package.to_code == "id"
        ),
        None,
    )
    if package is None:
        print("No English -> Indonesian Argos model was found in the package index.")
        print("Available packages targeting Indonesian:")
        for candidate in available_packages:
            if candidate.to_code == "id":
                print(f"  {candidate.from_code} -> {candidate.to_code}: {candidate}")
        sys.exit(2)

    download_path = package.download()
    argostranslate.package.install_from_path(download_path)

    test = argostranslate.translate.translate("The story begins at night.", "en", "id")
    print("Installed English -> Indonesian model.")
    print("Test:", test)
except Exception as exc:
    print(f"Failed to install English -> Indonesian model: {exc}")
    sys.exit(1)
'@

$installer | & $python -

Write-Host "Translation support installation finished. Restart StoryCut AI before using Voice -> ID Script."
