#!/usr/bin/env bash
# Таргетолог AI (локальный): каждый пользователь подключает СВОИ рекламные кабинеты
# (VK Ads / Meta / Google Ads / GA4) — ключи ложатся в его Keychain через
# configure_connectors, данные кампаний — только на его машине.
set -euo pipefail
VER="0.1.0-ffdb455"
ZIP="https://files.82-115-42-21.sslip.io/extella-targetologist-${VER}.zip"
DST="$HOME/extella-plugins/targetologist"
REG="$HOME/extella-plugins/_registry/targetologist_local.json"
PORT=34770
say(){ printf "  %s\n" "$*"; }

PY=""; for c in python3 python; do $c -c 'import sys;exit(0 if sys.version_info[:2]>=(3,11) else 1)' >/dev/null 2>&1 && { PY=$c; break; }; done
[ -n "$PY" ] || { say "~ Таргетолог пропущен: нужен Python 3.11+"; exit 0; }

# Машина владельца: основная установка targetologist_team — не дублируем.
if [ -f "$HOME/extella-plugins/_registry/targetologist_team.json" ]; then
  say "✓ Таргетолог: основная установка уже есть — локальная копия не нужна"; exit 0
fi

if [ -f "$DST/.version" ] && [ "$(cat "$DST/.version")" = "$VER" ] && [ -f "$REG" ]; then
  say "✓ Таргетолог ${VER} уже установлен"; exit 0
fi

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
curl -fsSL "$ZIP" -o "$TMP/tg.zip"
unzip -q "$TMP/tg.zip" -d "$TMP/src"
mkdir -p "$DST"
# Код заменяем целиком; данные (data/) и .version переживают обновление
find "$DST" -mindepth 1 -maxdepth 1 ! -name "data" ! -name ".version" -exec rm -rf {} +
cp -R "$TMP/src/." "$DST/"
echo "$VER" > "$DST/.version"
say "✓ код Таргетолога → $DST"

mkdir -p "$HOME/extella-plugins/_registry"
"$PY" - "$REG" "$DST" "$PORT" <<'PYJ'
import json, sys
reg, dst, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
card = {
  "id": "targetologist_local",
  "name": "Таргетолог AI (мой)",
  "tagline": "Мои рекламные кабинеты и кампании — данные только у меня",
  "description": "Локальный Таргетолог: брифы, медиапланы, черновики кампаний и отчёты. Подключите СВОИ кабинеты (VK Ads, Meta, Google Ads, GA4) — ключи лягут в ваш Keychain; внешние отправки только после approval.",
  "category": "analytics", "type": "custom", "version": "0.1.0", "mode": "repo_ui",
  "ui": {"type": "local_server", "port": port, "rootPath": dst,
         "mainFile": "index.html", "healthPath": "/health",
         "openInBrowser": False, "expectsHealth": True},
  "service": {"isApp": True, "port": port, "healthPath": "/health", "ready": True,
              "launchCmd": "%s/server.py (python3)" % dst},
}
json.dump(card, open(reg, "w"), ensure_ascii=False, indent=2)
PYJ
say "✓ карточка «Таргетолог AI (мой)» в реестре"

if ! nc -z 127.0.0.1 "$PORT" 2>/dev/null; then
  ( cd "$DST" && nohup "$PY" server.py >/tmp/extella_targetolog_local.log 2>&1 & )
  sleep 3
  nc -z 127.0.0.1 "$PORT" 2>/dev/null && say "✓ Таргетолог на :$PORT" || say "~ поднимется при открытии карточки"
fi
