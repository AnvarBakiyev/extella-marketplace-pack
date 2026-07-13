# Установка свежего тулбара Extella на Windows (подменяет toolbar.js).
$ErrorActionPreference = "Stop"
$url  = "https://raw.githubusercontent.com/AnvarBakiyev/extella-marketplace-pack/main/toolbar/toolbar.js"
$dest = Join-Path $env:APPDATA "extella-desktop\toolbar.js"
Write-Host "-> Extella toolbar update"
New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
if (Test-Path $dest) { Copy-Item $dest "$dest.bak" -Force; Write-Host "  ok: backup made" }
Invoke-WebRequest -Uri $url -OutFile "$dest.tmp"
if (-not (Select-String -Path "$dest.tmp" -Pattern "Extella Plugins" -Quiet)) { Remove-Item "$dest.tmp"; throw "check failed" }
Move-Item "$dest.tmp" $dest -Force
Write-Host "  ok: installed $dest"
Get-Process Extella -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 1
Write-Host "Done. Reopen Extella -> Plugins."
