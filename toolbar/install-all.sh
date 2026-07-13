#!/usr/bin/env bash
# Полный установщик Extella для коллег: ТУЛБАР + ЭКСПЕРТЫ тулбара + ВИЗАРД.
set -euo pipefail
PACK="https://github.com/AnvarBakiyev/extella-marketplace-pack/archive/refs/heads/main.tar.gz"
WIZ="https://github.com/AnvarBakiyev/extella-adoption-wizard/archive/refs/heads/main.tar.gz"
RAW="https://raw.githubusercontent.com/AnvarBakiyev/extella-marketplace-pack/main/toolbar"
APP="$HOME/Library/Application Support/extella-desktop"
WA="$HOME/extella_wizard/app"; AGENT="agent_extella_alibaba_default"
say(){ printf "\n\033[1m%s\033[0m\n" "$*"; }

say "1/5 Тулбар"
mkdir -p "$APP"; [ -f "$APP/toolbar.js" ] && cp "$APP/toolbar.js" "$APP/toolbar.js.bak.$(date +%s)"
curl -fsSL "$RAW/toolbar.js" -o "$APP/tb.tmp"
grep -q "Extella Plugins" "$APP/tb.tmp" || { echo "✗ toolbar check"; rm -f "$APP/tb.tmp"; exit 1; }
mv "$APP/tb.tmp" "$APP/toolbar.js"; echo "  ✓"

say "2/5 Токен"
TOKEN="${EXTELLA_TOKEN:-}"; [ -z "$TOKEN" ] && { printf "  Вставь Extella-токен: "; read -rs TOKEN; echo; }
if [ -z "$TOKEN" ] || printf '%s' "$TOKEN" | LC_ALL=C grep -q '[^ -~]\|[<> ]' || [ ${#TOKEN} -lt 20 ]; then
  echo "  ! Тулбар установлен. Эксперты/Визард пропущены: нужен НАСТОЯЩИЙ токен."; exit 0; fi
mkdir -p "$WA"
python3 - "$WA/config.json" "$TOKEN" "$AGENT" <<'PY'
import json,sys;json.dump({"auth_token":sys.argv[2],"api_base":"https://api.extella.ai","port":8765,"agent_id":sys.argv[3]},open(sys.argv[1],"w"),ensure_ascii=False,indent=2)
PY

say "3/5 Python"
PY=""; for c in python3 python; do $c -c 'import sys;exit(0 if sys.version_info[0]==3 else 1)' >/dev/null 2>&1 && { PY=$c; break; }; done
[ -z "$PY" ] && command -v brew >/dev/null && { brew install python@3.12 >/dev/null 2>&1 || true; command -v python3 >/dev/null && PY=python3; }
[ -n "$PY" ] || { echo "✗ Нужен Python 3 (python.org/downloads). Тулбар уже стоит."; exit 0; }
echo "  ✓ $($PY -V 2>&1)"

say "4/5 Эксперты тулбара + Визард"
TMP=$(mktemp -d)
curl -fsSL "$PACK" -o "$TMP/p.tgz"; tar -xzf "$TMP/p.tgz" -C "$TMP"
PD=$(find "$TMP" -maxdepth 1 -type d -name "extella-marketplace-pack*"|head -1)
( cd "$PD" && "$PY" install.py ) || echo "  ⚠️ pack install.py частично"
curl -fsSL "$WIZ" -o "$TMP/w.tgz"; tar -xzf "$TMP/w.tgz" -C "$TMP"
WD=$(find "$TMP" -maxdepth 1 -type d -name "extella-adoption-wizard*"|head -1)
cp "$WD/ui/"*.py "$WD/ui/wizard.html" "$WA/" 2>/dev/null || true
( cd "$WD" && "$PY" install.py ) || echo "  ⚠️ wizard install.py частично"
rm -rf "$TMP"

say "5/5 Запуск"
pkill -f "extella_wizard/app/server.py" 2>/dev/null || true
( cd "$WA" && nohup "$PY" server.py >/tmp/extella_wizard.log 2>&1 & ); sleep 2
curl -fsS http://127.0.0.1:8765/x/health >/dev/null 2>&1 && echo "  ✓ мост :8765" || echo "  ~ мост поднимется при открытии"
pkill -f "Extella.app" 2>/dev/null || true; sleep 1; open -a Extella 2>/dev/null || true
say "Готово ✓ — открой Extella → Plugins"
