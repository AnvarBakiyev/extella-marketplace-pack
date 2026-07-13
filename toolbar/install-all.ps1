# Полный установщик Extella (Windows): ТУЛБАР + ЭКСПЕРТЫ тулбара + ВИЗАРД.
$ErrorActionPreference="Stop"
$RAW="https://raw.githubusercontent.com/AnvarBakiyev/extella-marketplace-pack/main/toolbar"
$PACK="https://github.com/AnvarBakiyev/extella-marketplace-pack/archive/refs/heads/main.zip"
$WIZ="https://github.com/AnvarBakiyev/extella-adoption-wizard/archive/refs/heads/main.zip"
$APP=Join-Path $env:APPDATA "extella-desktop"
$WA=Join-Path $env:USERPROFILE "extella_wizard\app"; $AGENT=if($env:EXTELLA_AGENT_ID){$env:EXTELLA_AGENT_ID}else{"agent_extella_alibaba_default"}
function Dl($u,$o){ Invoke-WebRequest $u -OutFile $o -UseBasicParsing }

Write-Host "1/5 Toolbar"
New-Item -ItemType Directory -Force -Path $APP | Out-Null
$dest=Join-Path $APP "toolbar.js"; if(Test-Path $dest){Copy-Item $dest "$dest.bak" -Force}
Dl "$RAW/toolbar.js" "$dest.tmp"
if(-not (Select-String -Path "$dest.tmp" -Pattern "Extella Plugins" -Quiet)){Remove-Item "$dest.tmp";throw "toolbar check failed"}
Move-Item "$dest.tmp" $dest -Force; Write-Host "  ok"

Write-Host "2/5 Token"
$tok=$env:EXTELLA_TOKEN
if(-not $tok){$s=Read-Host "  Paste Extella token" -AsSecureString;$tok=[Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))}
if((-not $tok)-or($tok -match '[^\x21-\x7E]')-or($tok -match '[<>\s]')-or($tok.Length -lt 20)){
  Write-Host "  ! Toolbar installed. Experts/Wizard skipped: need a REAL token." -ForegroundColor Yellow; return }
New-Item -ItemType Directory -Force -Path $WA | Out-Null
$cfg=@{auth_token=$tok;api_base="https://api.extella.ai";port=8765;agent_id=$AGENT}|ConvertTo-Json
[IO.File]::WriteAllText((Join-Path $WA "config.json"),$cfg,(New-Object System.Text.UTF8Encoding($false)))

Write-Host "3/5 Python"
function Get-Py{foreach($c in @("py -3","python","python3")){try{$v=(cmd /c "$c --version" 2>&1);if($LASTEXITCODE -eq 0 -and "$v" -match "Python 3"){return $c}}catch{}};return $null}
$py=Get-Py
if(-not $py){Write-Host "  installing Python via winget...";try{winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements|Out-Null}catch{};$env:Path=[Environment]::GetEnvironmentVariable("Path","Machine")+";"+[Environment]::GetEnvironmentVariable("Path","User");$py=Get-Py}
if(-not $py){Write-Host "  ! Wizard skipped: install Python 3 (python.org/downloads, tick Add to PATH) and re-run. Toolbar works now." -ForegroundColor Yellow;return}
Write-Host "  ok: $py"
try{ & cmd /c "$py -m pip install --quiet --disable-pip-version-check certifi" | Out-Null }catch{}
try{ $cb = (& cmd /c "$py -c ""import certifi;print(certifi.where())"""); if($cb){ $env:SSL_CERT_FILE=$cb.Trim() } }catch{}

Write-Host "4/5 Toolbar experts + Wizard"
$tmp=Join-Path $env:TEMP ("ex_"+[guid]::NewGuid());New-Item -ItemType Directory -Force -Path $tmp|Out-Null
Dl $PACK "$tmp\p.zip"; Expand-Archive "$tmp\p.zip" -DestinationPath $tmp -Force
$pd=(Get-ChildItem $tmp -Directory|Where-Object{$_.Name -like "extella-marketplace-pack*"}|Select-Object -First 1).FullName
Push-Location $pd; & cmd /c "$py install.py"; Pop-Location
Dl $WIZ "$tmp\w.zip"; Expand-Archive "$tmp\w.zip" -DestinationPath $tmp -Force
$wd=(Get-ChildItem $tmp -Directory|Where-Object{$_.Name -like "extella-adoption-wizard*"}|Select-Object -First 1).FullName
Copy-Item (Join-Path $wd "ui\*") $WA -Force
Push-Location $wd; & cmd /c "$py install.py"; Pop-Location
Remove-Item $tmp -Recurse -Force

Write-Host "5/5 Start"
Start-Process -FilePath ($py.Split(' ')[0]) -ArgumentList (($py.Split(' ')[1..9]+(Join-Path $WA "server.py")) -join ' ') -WindowStyle Hidden
Start-Sleep 3
try{Invoke-WebRequest "http://127.0.0.1:8765/x/health" -TimeoutSec 5 -UseBasicParsing|Out-Null;Write-Host "  ok: bridge up"}catch{Write-Host "  ~ bridge starts on open"}
Get-Process Extella -ErrorAction SilentlyContinue|Stop-Process -Force;Start-Sleep 1
Write-Host "DONE. Open Extella -> Plugins -> Desktop."
