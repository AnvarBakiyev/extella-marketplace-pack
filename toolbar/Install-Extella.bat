@echo off
title Extella Installer
echo === Extella: установка тулбара + Визарда ===
echo.
echo Шаг 2 (в PowerShell): сначала токен, затем id своего Qwen-агента (копия базового Qwen, начинается с agent_).
echo id агента можно пропустить (Enter) - тогда только витрина без Визард-чата.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$t=Read-Host 'Вставь Extella-токен'; if(-not $t){Write-Host 'Токен пуст.';exit}; $a=Read-Host 'Вставь id Qwen-агента (agent_...) или Enter'; $env:EXTELLA_TOKEN=$t; $env:EXTELLA_AGENT_ID=$a; irm https://raw.githubusercontent.com/AnvarBakiyev/extella-marketplace-pack/main/toolbar/install-all.ps1 | iex"
echo.
echo Готово. Открой Extella - Plugins.
pause
