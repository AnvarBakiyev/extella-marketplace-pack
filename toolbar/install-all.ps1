# Единый установщик Extella (Windows): ТУЛБАР + ВИЗАРД (мост :8765).
# Запуск:  $env:EXTELLA_TOKEN="<реальный токен>"; irm https://raw.githubusercontent.com/AnvarBakiyev/extella-marketplace-pack/main/toolbar/install-all.ps1 | iex
$ErrorActionPreference = "Stop"
$RAW="https://raw.githubusercontent.com/AnvarBakiyev/extella-marketplace-pack/main/toolbar"
$WIZ="https://github.com/AnvarBakiyev/extella-adoption-wizard/archive/refs/heads/main.zip"
$APP=Join-Path $env:APPDATA "extella-desktop"
$WA=Join-Path $env:USERPROFILE "extella_wizard\app"
$AGENT="agent_extella_alibaba_default"

# ── 1. ТУЛБАР ─────────────────────────────────────────────────────────────
Write-Host "1/4 Toolbar"
New-Item -ItemType Directory -Force -Path $APP | Out-Null
$dest=Join-Path $APP "toolbar.js"
if (Test-Path $dest) { Copy-Item $dest "$dest.bak" -Force }
Invoke-WebRequest "$RAW/toolbar.js" -OutFile "$dest.tmp"
if (-not (Select-String -Path "$dest.tmp" -Pattern "Extella Plugins" -Quiet)) { Remove-Item "$dest.tmp"; throw "toolbar check failed" }
Move-Item "$dest.tmp" $dest -Force; Write-Host "  ok: toolbar installed"

# ── 2. ТОКЕН ──────────────────────────────────────────────────────────────
Write-Host "2/4 Token"
$tok = $env:EXTELLA_TOKEN
if (-not $tok) { $sec = Read-Host "  Paste your Extella token" -AsSecureString; $tok=[Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)) }
if ((-not $tok) -or ($tok -match '[^\x21-\x7E]') -or ($tok -match '[<>\s]') -or ($tok.Length -lt 20)) {
  Write-Host "  ! Toolbar installed, but Wizard skipped: need a REAL token (not the placeholder)." -ForegroundColor Yellow
  Write-Host "  Re-run with your token. Toolbar already works: open Extella -> Plugins."; return
}

# ── 3. PYTHON (настоящий, не заглушка Store) + авто-установка ──────────────
Write-Host "3/4 Python + Wizard"
function Get-Py {
  foreach ($c in @("py -3","python","python3")) {
    try { $v = (cmd /c "$c --version" 2>&1); if ($LASTEXITCODE -eq 0 -and "$v" -match "Python 3") { return $c } } catch {}
  }
  return $null
}
$py = Get-Py
if (-not $py) {
  Write-Host "  Python 3 not found — trying winget..."
  try { winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements | Out-Null } catch {}
  $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine")+";"+[Environment]::GetEnvironmentVariable("Path","User")
  $py = Get-Py
}
if (-not $py) {
  Write-Host "  ! Wizard skipped: install Python 3 from https://www.python.org/downloads/ (tick 'Add to PATH'), then re-run." -ForegroundColor Yellow
  Write-Host "  Toolbar is installed and works now."; return
}
Write-Host "  Python: $py"

# Мост + config + install.py
$tmp=Join-Path $env:TEMP ("wiz_"+[guid]::NewGuid()); New-Item -ItemType Directory -Force -Path $tmp | Out-Null
Invoke-WebRequest $WIZ -OutFile "$tmp\w.zip"; Expand-Archive "$tmp\w.zip" -DestinationPath $tmp -Force
$src=(Get-ChildItem $tmp -Directory | Where-Object { $_.Name -like "extella-adoption-wizard*" } | Select-Object -First 1).FullName
New-Item -ItemType Directory -Force -Path $WA | Out-Null
Copy-Item (Join-Path $src "ui\*") $WA -Force
$cfgJson = @{auth_token=$tok;api_base="https://api.extella.ai";port=8765;agent_id=$AGENT} | ConvertTo-Json
[System.IO.File]::WriteAllText((Join-Path $WA "config.json"), $cfgJson, (New-Object System.Text.UTF8Encoding($false)))
Push-Location $src; & cmd /c "$py install.py"; $rc=$LASTEXITCODE; Pop-Location
Remove-Item $tmp -Recurse -Force
if ($rc -ne 0) { Write-Host "  ! install.py вернул код $rc — возможно SSL/сеть. Пришли вывод." -ForegroundColor Yellow }

# ── 4. Запуск моста + перезапуск ──────────────────────────────────────────
Write-Host "4/4 Start"
Start-Process -FilePath ($py.Split(' ')[0]) -ArgumentList (($py.Split(' ')[1..9] + (Join-Path $WA "server.py")) -join ' ') -WindowStyle Hidden
Start-Sleep 3
try { $h=Invoke-WebRequest "http://127.0.0.1:8765/x/health" -TimeoutSec 5; Write-Host "  ok: bridge up (:8765)" } catch { Write-Host "  ~ bridge not answering yet — app will start it on open" }
Get-Process Extella -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 1
Write-Host "DONE. Open Extella -> Plugins -> Desktop -> 'My computer / Wizard'."
