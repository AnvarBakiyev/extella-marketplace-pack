#!/usr/bin/env bash
# Единый установщик Extella для коллег: ТУЛБАР (новая витрина) + ВИЗАРД (мост :8765).
# Использование:
#   EXTELLA_TOKEN=<твой_токен> bash <(curl -fsSL https://raw.githubusercontent.com/AnvarBakiyev/extella-marketplace-pack/main/toolbar/install-all.sh)
# Токен можно не задавать в переменной — скрипт спросит. Токен нигде не печатается.
set -euo pipefail
RAW="https://raw.githubusercontent.com/AnvarBakiyev/extella-marketplace-pack/main/toolbar"
WIZ_REPO="https://github.com/AnvarBakiyev/extella-adoption-wizard"
APP_DIR="$HOME/Library/Application Support/extella-desktop"
WIZ_APP="$HOME/extella_wizard/app"
KEYLESS_AGENT="agent_extella_alibaba_default"   # платформенный Qwen (keyless) — без ручных копий агентов

say(){ printf "\n\033[1m%s\033[0m\n" "$*"; }

# ── 0. Предусловия ────────────────────────────────────────────────────────
command -v curl >/dev/null || { echo "нужен curl"; exit 1; }
PY=""
for c in python3 python; do if $c -c 'import sys;exit(0 if sys.version_info[0]==3 else 1)' >/dev/null 2>&1; then PY=$c; break; fi; done
if [ -z "$PY" ]; then
  if command -v brew >/dev/null; then say "Python 3 не найден — ставлю через brew"; brew install python@3.12 >/dev/null 2>&1 || true; command -v python3 >/dev/null && PY=python3; fi
fi
[ -n "$PY" ] || { echo "✗ Нужен Python 3 (для моста Визарда). Поставь: https://www.python.org/downloads/ и повтори. Тулбар уже стоит."; exit 0; }
say "Python: $($PY -V 2>&1)"

# ── 1. ТУЛБАР ─────────────────────────────────────────────────────────────
say "1/4 · Тулбар"
mkdir -p "$APP_DIR"
[ -f "$APP_DIR/toolbar.js" ] && cp "$APP_DIR/toolbar.js" "$APP_DIR/toolbar.js.bak.$(date +%s)" && echo "  ✓ бэкап"
curl -fsSL "$RAW/toolbar.js" -o "$APP_DIR/toolbar.js.tmp"
grep -q "Extella Plugins" "$APP_DIR/toolbar.js.tmp" || { echo "  ✗ проверка тулбара не прошла"; rm -f "$APP_DIR/toolbar.js.tmp"; exit 1; }
mv "$APP_DIR/toolbar.js.tmp" "$APP_DIR/toolbar.js"
echo "  ✓ тулбар установлен"

# ── 2. Токен ──────────────────────────────────────────────────────────────
say "2/4 · Токен Extella (для Визарда)"
TOKEN="${EXTELLA_TOKEN:-}"
if [ -z "$TOKEN" ]; then
  printf "  Вставь свой Extella-токен и нажми Enter: "
  read -rs TOKEN; echo
fi
if [ -z "$TOKEN" ] || printf '%s' "$TOKEN" | LC_ALL=C grep -q '[^ -~]\|[<> ]' || [ ${#TOKEN} -lt 20 ]; then
  echo "  ! Тулбар установлен. Визард пропущен: нужен НАСТОЯЩИЙ токен (не плейсхолдер). Перезапусти с токеном."; exit 0
fi

# ── 3. ВИЗАРД: мост + config + регистрация ────────────────────────────────
say "3/4 · Визард (мост :8765)"
TMP=$(mktemp -d)
curl -fsSL "$WIZ_REPO/archive/refs/heads/main.tar.gz" -o "$TMP/wiz.tgz"
tar -xzf "$TMP/wiz.tgz" -C "$TMP"
SRC=$(find "$TMP" -maxdepth 1 -type d -name "extella-adoption-wizard*" | head -1)
mkdir -p "$WIZ_APP"
cp "$SRC/ui/"*.py "$SRC/ui/wizard.html" "$WIZ_APP/" 2>/dev/null || true
python3 - "$WIZ_APP/config.json" "$TOKEN" "$KEYLESS_AGENT" <<'PY'
import json,sys
path,token,agent=sys.argv[1],sys.argv[2],sys.argv[3]
json.dump({"auth_token":token,"api_base":"https://api.extella.ai","port":8765,"agent_id":agent},
          open(path,"w"),ensure_ascii=False,indent=2)
print("  ✓ config.json (keyless Qwen)")
PY
( cd "$SRC" && "$PY" install.py ) || echo "  ⚠️ install.py частично (эксперты, возможно, уже глобальные — норм)"
rm -rf "$TMP"

# ── 4. Запуск моста + перезапуск приложения ───────────────────────────────
say "4/4 · Запуск"
pkill -f "extella_wizard/app/server.py" 2>/dev/null || true
( cd "$WIZ_APP" && nohup "$PY" server.py >/tmp/extella_wizard.log 2>&1 & )
sleep 2
curl -fsS http://127.0.0.1:8765/x/health >/dev/null 2>&1 && echo "  ✓ мост Визарда поднят (:8765)" || echo "  ⚠️ мост не ответил сразу — приложение поднимет его при открытии"
pkill -f "Extella.app" 2>/dev/null || true; sleep 1; open -a Extella 2>/dev/null || true

say "Готово ✓"
echo "Открой Extella → Plugins → Рабочий стол. Кнопка «Мой компьютер · Визард» откроет Визард."
