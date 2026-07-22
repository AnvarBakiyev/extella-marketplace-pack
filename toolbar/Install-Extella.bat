@echo off
setlocal
PowerShell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-all.ps1" %*
exit /b %ERRORLEVEL%
