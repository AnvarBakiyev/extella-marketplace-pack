@echo off
title Extella Installer
echo === Extella: установка тулбара + Визарда ===
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$t = Read-Host 'Вставь свой Extella-токен и нажми Enter'; if(-not $t){Write-Host 'Токен пуст.'; exit}; $env:EXTELLA_TOKEN=$t; irm https://raw.githubusercontent.com/AnvarBakiyev/extella-marketplace-pack/main/toolbar/install-all.ps1 | iex"
echo.
echo Готово. Открой Extella - Plugins.
pause
