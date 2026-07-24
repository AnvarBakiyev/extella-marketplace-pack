#!/usr/bin/env bash
# Predictive Sales (локальный): каждый пользователь подключает СВОЮ CRM Bitrix24.
# Код раздаётся zip'ом с VPS; webhook хранится в Keychain пользователя (macOS),
# данные воронки — только на его машине. Данных/секретов владельца в дистрибутиве нет.
set -euo pipefail
VER="0.1.0-4e19dc5"
ZIP="https://files.82-115-42-21.sslip.io/extella-predictive-sales-${VER}.zip"
DST="$HOME/extella-plugins/predictive_sales"
REG="$HOME/extella-plugins/_registry/extella_predictive_sales_local.json"
PORT=8791
say(){ printf "  %s\n" "$*"; }

PY=""; for c in python3 python; do $c -c 'import sys;exit(0 if sys.version_info[:2]>=(3,11) else 1)' >/dev/null 2>&1 && { PY=$c; break; }; done
[ -n "$PY" ] || { say "~ Predictive Sales пропущен: нужен Python 3.11+"; exit 0; }

# Машина владельца: тут живёт основная разработческая установка — не дублируем.
if [ -f "$HOME/extella-plugins/_registry/extella_predictive_sales.json" ]; then
  say "✓ Predictive Sales: основная установка уже есть — локальная копия не нужна"; exit 0
fi

if [ -f "$DST/.version" ] && [ "$(cat "$DST/.version")" = "$VER" ] && [ -f "$REG" ]; then
  say "✓ Predictive Sales ${VER} уже установлен"; exit 0
fi

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
curl -fsSL "$ZIP" -o "$TMP/ps.zip"
unzip -q "$TMP/ps.zip" -d "$TMP/src"
mkdir -p "$DST"
# Код заменяем целиком; данные (.state) и .version переживают обновление
find "$DST" -mindepth 1 -maxdepth 1 ! -name ".state" ! -name ".version" -exec rm -rf {} +
cp -R "$TMP/src/." "$DST/"
echo "$VER" > "$DST/.version"
say "✓ код Predictive Sales → $DST"

mkdir -p "$HOME/extella-plugins/_registry"
# Явная (пере)установка снимает user-тумбстоун — иначе синк сочтёт карточку удалённой
rm -f "$HOME/extella-plugins/_registry/_removed/extella_predictive_sales_local.json"
"$PY" - "$REG" "$DST" "$PORT" <<'PYJ'
import json, sys
reg, dst, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
card = {
  "id": "extella_predictive_sales_local",
  "name": "Predictive Sales (мой)",
  "tagline": "Моя воронка Bitrix24 с AI-прогнозами — данные только у меня",
  "description": "Локальный кокпит Predictive Sales: подключите СВОЙ входящий webhook Bitrix24 во вкладке «Подключения» кокпита — он ляжет в ваш Keychain. Воронка, рабочие шансы, риски и следующие действия; записи в CRM только после подтверждения.",
  "category": "analytics", "type": "custom", "version": "0.1.0", "mode": "repo_ui",
  "ui": {"type": "local_server", "port": port, "rootPath": dst,
         "mainFile": "index.html", "healthPath": "/api/health",
         "openInBrowser": False, "expectsHealth": True},
  "service": {"isApp": True, "port": port, "healthPath": "/api/health", "ready": True,
              "launchCmd": "%s/plugin/cockpit_server.py --port %d (python3)" % (dst, port)},
}
json.dump(card, open(reg, "w"), ensure_ascii=False, indent=2)
PYJ
say "✓ карточка «Predictive Sales (мой)» в реестре"

if ! nc -z 127.0.0.1 "$PORT" 2>/dev/null; then
  ( cd "$DST" && nohup "$PY" plugin/cockpit_server.py --port "$PORT" >/tmp/extella_ps_local.log 2>&1 & )
  sleep 3
  nc -z 127.0.0.1 "$PORT" 2>/dev/null && say "✓ кокпит на :$PORT" || say "~ кокпит поднимется при открытии карточки"
fi
