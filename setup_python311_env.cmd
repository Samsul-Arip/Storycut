@echo off
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0setup_python311_env.ps1"
echo.
echo If setup finished successfully, restart StoryCut AI from the desktop icon.
pause
