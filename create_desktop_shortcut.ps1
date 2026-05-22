$ErrorActionPreference = "Stop"

$appDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $appDir "launch_storycut_ai.vbs"
$pythonIcon311 = Join-Path $appDir ".venv311\Scripts\pythonw.exe"
$pythonIcon = Join-Path $appDir ".venv\Scripts\pythonw.exe"
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "StoryCut AI.lnk"

if (-not (Test-Path -LiteralPath $launcher)) {
    throw "Launcher not found: $launcher"
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "$env:WINDIR\System32\wscript.exe"
$shortcut.Arguments = "`"$launcher`""
$shortcut.WorkingDirectory = $appDir
$shortcut.Description = "Launch StoryCut AI without opening a terminal"

if (Test-Path -LiteralPath $pythonIcon311) {
    $shortcut.IconLocation = "$pythonIcon311,0"
} elseif (Test-Path -LiteralPath $pythonIcon) {
    $shortcut.IconLocation = "$pythonIcon,0"
} else {
    $shortcut.IconLocation = "$env:WINDIR\System32\shell32.dll,167"
}

$shortcut.Save()
Write-Host "Created desktop shortcut: $shortcutPath"
