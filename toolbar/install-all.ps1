# Единый установщик Extella (Windows): ТУЛБАР + ВИЗАРД (мост :8765).
# Запуск:  $env:EXTELLA_TOKEN="<токен>"; irm https://raw.githubusercontent.com/AnvarBakiyev/extella-marketplace-pack/main/toolbar/install-all.ps1 | iex
$ErrorActionPreference = "Stop"
$RAW="https://raw.githubusercontent.com/AnvarBakiyev/extella-marketplace-pack/main/toolbar"
$WIZ="https://github.com/AnvarBakiyev/extella-adoption-wizard/archive/refs/heads/main.zip"
$APP=Join-Path $env:APPDATA "extella-desktop"
$WA=Join-Path $env:USERPROFILE "extella_wizard\app"
$AGENT="agent_extella_alibaba_default"

Write-Host "1/4 Toolbar"
New-Item -ItemType Directory -Force -Path $APP | Out-Null
$dest=Join-Path $APP "toolbar.js"
if (Test-Path $dest) { Copy-Item $dest "$dest.bak" -Force }
Invoke-WebRequest "$RAW/toolbar.js" -OutFile "$dest.tmp"
if (-not (Select-String -Path "$dest.tmp" -Pattern "Extella Plugins" -Quiet)) { Remove-Item "$dest.tmp"; throw "toolbar check failed" }
Move-Item "$dest.tmp" $dest -Force; Write-Host "  ok"

Write-Host "2/4 Token"
$tok = $env:EXTELLA_TOKEN
if (-not $tok) { $sec = Read-Host "  Paste your Extella token" -AsSecureString; $tok=[Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)) }
if (-not $tok) { throw "empty token" }

Write-Host "3/4 Wizard bridge"
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Python 3 required (python.org/downloads)" }
$tmp=Join-Path $env:TEMP ("wiz_"+[guid]::NewGuid()); New-Item -ItemType Directory -Force -Path $tmp | Out-Null
Invoke-WebRequest $WIZ -OutFile "$tmp\w.zip"; Expand-Archive "$tmp\w.zip" -DestinationPath $tmp -Force
$src=Get-ChildItem $tmp -Directory | Where-Object { $_.Name -like "extella-adoption-wizard*" } | Select-Object -First 1
New-Item -ItemType Directory -Force -Path $WA | Out-Null
Copy-Item (Join-Path $src.FullName "ui\*") $WA -Force
$cfg=@{auth_token=$tok;api_base="https://api.extella.ai";port=8765;agent_id=$AGENT} | ConvertTo-Json
Set-Content -Path (Join-Path $WA "config.json") -Value $cfg -Encoding UTF8
Push-Location $src.FullName; python install.py; Pop-Location
Remove-Item $tmp -Recurse -Force

Write-Host "4/4 Start"
Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path } | Out-Null
Start-Process python -ArgumentList (Join-Path $WA "server.py") -WindowStyle Hidden
Start-Sleep 2
Get-Process Extella -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 1
Write-Host "Done. Open Extella -> Plugins -> Desktop."
