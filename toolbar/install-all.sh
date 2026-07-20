#!/usr/bin/env bash
# Полный установщик Extella для коллег: ТУЛБАР + ЭКСПЕРТЫ тулбара + ВИЗАРД.
set -euo pipefail
PACK="https://github.com/AnvarBakiyev/extella-marketplace-pack/archive/refs/heads/main.tar.gz"
WIZARD_REF="${EXTELLA_WIZARD_REF:-codex/prod-hardening}"
WIZ="https://github.com/AnvarBakiyev/extella-adoption-wizard/archive/refs/heads/${WIZARD_REF}.tar.gz"
WIZ_API="https://api.github.com/repos/AnvarBakiyev/extella-adoption-wizard/commits/$(printf '%s' "$WIZARD_REF" | sed 's|/|%2F|g')"
RAW="https://raw.githubusercontent.com/AnvarBakiyev/extella-marketplace-pack/main/toolbar"
APP="$HOME/Library/Application Support/extella-desktop"
WA="$HOME/extella_wizard/app"; AGENT="${EXTELLA_AGENT_ID:-agent_extella_alibaba_default}"
say(){ printf "\n\033[1m%s\033[0m\n" "$*"; }

say "QA-сборка Extella · визард: ${WIZARD_REF}"

say "1/5 Тулбар"
mkdir -p "$APP"; [ -f "$APP/toolbar.js" ] && cp "$APP/toolbar.js" "$APP/toolbar.js.bak.$(date +%s)"
curl -fsSL "$RAW/toolbar.js" -o "$APP/tb.tmp"
grep -q "Extella Plugins" "$APP/tb.tmp" || { echo "✗ toolbar check"; rm -f "$APP/tb.tmp"; exit 1; }
mv "$APP/tb.tmp" "$APP/toolbar.js"; echo "  ✓"

say "2/5 Токен"
TOKEN="${EXTELLA_TOKEN:-}"
if [ -z "$TOKEN" ]; then printf "  Вставь Extella-токен и нажми Enter: "; read -r TOKEN </dev/tty || true; fi
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
# macOS python.org Python часто без CA-сертификатов. Ставим certifi И привязываем его к дефолтному
# пути Python (аналог "Install Certificates.command") — тогда SSL работает для ВСЕХ python-процессов,
# включая мост server.py, который приложение запускает само. Проверка SSL остаётся включённой.
"$PY" -m pip install --quiet --disable-pip-version-check certifi >/dev/null 2>&1 || true
"$PY" - <<'PYCERT' 2>/dev/null || true
import os, ssl, certifi
cf = ssl.get_default_verify_paths().openssl_cafile
d = os.path.dirname(cf)
try:
    if d and not os.path.isdir(d): os.makedirs(d, exist_ok=True)
    try: os.remove(cf)
    except FileNotFoundError: pass
    except IsADirectoryError: pass
    os.symlink(certifi.where(), cf)
    print("  linked CA ->", cf)
except PermissionError:
    print("  no perm to link CA (fallback env)")
except Exception as e:
    print("  CA:", e)
PYCERT
CB=$("$PY" -c "import certifi;print(certifi.where())" 2>/dev/null || true)
[ -n "$CB" ] && export SSL_CERT_FILE="$CB"
echo "  ✓ SSL-сертификаты (certifi)"

# Движки инструментов: Homebrew (CLI: PDF/OCR/конвертеры) + Node (MCP-серверы). Тяжёлое + просит пароль — по согласию.
if [ "$(uname)" = "Darwin" ] && ! command -v brew >/dev/null 2>&1 && [ ! -x /opt/homebrew/bin/brew ] && [ ! -x /usr/local/bin/brew ]; then
  printf "  Поставить движки инструментов (Homebrew — для CLI; Node — для MCP-серверов)? Спросит пароль один раз [y/N]: "
  read -r _hb </dev/tty || _hb=""
  case "$_hb" in y|Y|д|Д|yes|да)
    NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" </dev/tty >/dev/null 2>&1 && echo "  ✓ Homebrew" || echo "  ~ Homebrew не поставился (CLI/MCP можно поставить позже)"
    _BREW=$(command -v brew || echo /opt/homebrew/bin/brew)
    [ -x "$_BREW" ] && { command -v node >/dev/null 2>&1 || "$_BREW" install node >/dev/null 2>&1 && echo "  ✓ Node (для MCP)" || true; };;
    *) echo "  пропущено (CLI/MCP потребуют Homebrew+Node позже)";;
  esac
fi

say "4/5 Эксперты тулбара + Визард"
TMP=$(mktemp -d)
curl -fsSL "$PACK" -o "$TMP/p.tgz"; tar -xzf "$TMP/p.tgz" -C "$TMP"
PD=$(find "$TMP" -maxdepth 1 -type d -name "extella-marketplace-pack*"|head -1)
( cd "$PD" && "$PY" install.py ) || echo "  ⚠️ pack install.py частично"
# Activity Center: панель уже в toolbar.js; ставим мост+наблюдатель (LaunchAgent) на macOS
if [ "$(uname)" = "Darwin" ] && [ -f "$PD/device/activity-center/install.py" ]; then
  "$PY" "$PD/device/activity-center/install.py" >/dev/null 2>&1 && echo "  \u2713 Activity Center (\u043c\u043e\u0441\u0442 :8799)" || echo "  ~ Activity Center \u043f\u0440\u043e\u043f\u0443\u0449\u0435\u043d"
fi
curl -fsSL "$WIZ" -o "$TMP/w.tgz"; tar -xzf "$TMP/w.tgz" -C "$TMP"
WD=$(find "$TMP" -maxdepth 1 -type d -name "extella-adoption-wizard*"|head -1)
cp "$WD/ui/"*.py "$WD/ui/wizard.html" "$WA/" 2>/dev/null || true
( cd "$WD" && "$PY" install.py ) || echo "  ⚠️ wizard install.py частично"
QA_SHA=$(curl -fsSL "$WIZ_API" 2>/dev/null | "$PY" -c 'import json,sys; print((json.load(sys.stdin) or {}).get("sha", ""))' 2>/dev/null || true)
[ -n "$QA_SHA" ] && printf '%s\n' "$QA_SHA" > "$WA/.qa_revision"
rm -rf "$TMP"

say "5/5 Запуск"
pkill -f "extella_wizard/app/server.py" 2>/dev/null || true
( cd "$WA" && nohup "$PY" server.py >/tmp/extella_wizard.log 2>&1 & ); sleep 2
HEALTH=$(curl -fsS http://127.0.0.1:8765/x/health 2>/dev/null || true)
VER=$(printf '%s' "$HEALTH" | "$PY" -c 'import json,sys; print((json.load(sys.stdin) or {}).get("version", ""))' 2>/dev/null || true)
[ -n "$VER" ] && echo "  ✓ мост :8765 · версия $VER · QA $WIZARD_REF" || echo "  ~ мост поднимется при открытии"
pkill -f "Extella.app" 2>/dev/null || true; sleep 1; open -a Extella 2>/dev/null || true
say "Готово ✓ — открой Extella → Plugins"
