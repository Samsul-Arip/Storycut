$ErrorActionPreference = "Stop"

$appDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvDir = Join-Path $appDir ".venv311"
$venvPython = Join-Path $venvDir "Scripts\python.exe"

function Test-Python311 {
    try {
        $output = & py -3.11 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
    } catch {
        return $false
    }
    if ($LASTEXITCODE -ne 0) {
        return $false
    }
    return ($output -eq "3.11")
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
    }
}

if (-not (Test-Python311)) {
    Write-Host "Python 3.11 was not found. Installing Python 3.11 with Python Install Manager..."
    & py install -y 3.11
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Python Install Manager failed; trying winget..."
        Invoke-Checked "winget" "install" "-e" "--id" "Python.Python.3.11" "--accept-source-agreements" "--accept-package-agreements"
    }
}

if (-not (Test-Python311)) {
    throw "Python 3.11 is still not available. Close this window, open a new PowerShell, and run setup_python311_env.cmd again. If it still fails, install Python 3.11 manually from python.org."
}

Write-Host "Creating Python 3.11 virtual environment: $venvDir"
if ((Test-Path -LiteralPath $venvDir) -and -not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "Existing .venv311 is incomplete; recreating it."
    $resolvedRoot = (Resolve-Path -LiteralPath $appDir).Path
    $targetFullPath = [System.IO.Path]::GetFullPath($venvDir)
    if (-not $targetFullPath.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove path outside app folder: $targetFullPath"
    }
    Remove-Item -LiteralPath $venvDir -Recurse -Force
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    Invoke-Checked "py" "-3.11" "-m" "venv" $venvDir
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Virtual environment was not created correctly. Missing: $venvPython"
}

Write-Host "Upgrading pip/setuptools/wheel..."
Invoke-Checked $venvPython "-m" "pip" "install" "--upgrade" "pip" "setuptools" "wheel"

Write-Host "Installing StoryCut AI requirements..."
Invoke-Checked $venvPython "-m" "pip" "install" "--timeout" "120" "--retries" "10" "-r" (Join-Path $appDir "requirements.txt")

Write-Host "Refreshing desktop shortcut..."
Invoke-Checked "powershell" "-ExecutionPolicy" "Bypass" "-File" (Join-Path $appDir "create_desktop_shortcut.ps1")

Write-Host ""
Write-Host "Python 3.11 environment is ready. Restart StoryCut AI from the desktop icon."
