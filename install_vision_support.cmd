@echo off
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0install_vision_support.ps1"
echo.
echo If the install finished successfully, restart StoryCut AI.
pause
