#!/usr/bin/env bash
# Kazakh Lawyer / «Агент по договорам»: проверка и согласование договоров
# с контролем человека. Код раздаётся zip'ом с VPS; документы и база — только
# на машине пользователя, в дистрибутиве данных нет.
set -euo pipefail
VER="0.1.0-2b41d94"
ZIP="https://files.82-115-42-21.sslip.io/extella-contract-agent-${VER}.zip"
DST="$HOME/extella-plugins/extella_contract_agent"
REG="$HOME/extella-plugins/_registry/extella_contract_agent.json"
PORT=8767
say(){ printf "  %s\n" "$*"; }

PY=""; for c in python3 python; do $c -c 'import sys;exit(0 if sys.version_info[:2]>=(3,10) else 1)' >/dev/null 2>&1 && { PY=$c; break; }; done
[ -n "$PY" ] || { say "~ Агент по договорам пропущен: нужен Python 3.10+"; exit 0; }

# Машина владельца: карточка есть, а нашего .version нет — это основная
# установка (боевые kb/ и out/), не трогаем.
if [ -f "$REG" ] && [ ! -f "$DST/.version" ]; then
  say "✓ Агент по договорам: основная установка уже есть — не трогаю"; exit 0
fi

if [ -f "$DST/.version" ] && [ "$(cat "$DST/.version")" = "$VER" ] && [ -f "$REG" ]; then
  say "✓ Агент по договорам ${VER} уже установлен"; exit 0
fi

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
curl -fsSL "$ZIP" -o "$TMP/ca.zip"
mkdir -p "$DST"
unzip -qo "$TMP/ca.zip" -d "$DST"
echo "$VER" > "$DST/.version"
say "✓ код Агента по договорам → $DST"

mkdir -p "$HOME/extella-plugins/_registry"
# Явная (пере)установка снимает user-тумбстоун — иначе синк сочтёт карточку удалённой
rm -f "$HOME/extella-plugins/_registry/_removed/extella_contract_agent.json"
"$PY" - "$REG" "$DST" "$PORT" <<'PYJ'
import json, sys
reg, dst, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
card = {
  "id": "extella_contract_agent",
  "name": "Агент по договорам",
  "tagline": "Проверка и согласование договоров — с контролем человека",
  "description": "Kazakh Lawyer: загрузите договор — агент найдёт риски и подготовит протокол разногласий. Внешняя отправка — только черновики, отправляет человек. Документы остаются на вашей машине.",
  "category": "docs", "type": "custom", "version": "0.1.0", "mode": "repo_ui",
  "ui": {"type": "local_server", "port": port, "rootPath": dst,
         "startExpert": "_etb_srv_extella_contracts",
         "mainFile": "index.html", "openInBrowser": False, "expectsHealth": False},
  "service": {"isApp": True, "port": port,
              "startExpert": "_etb_srv_extella_contracts",
              "launchCmd": "%s/server.py (python3)" % dst, "ready": True},
}
json.dump(card, open(reg, "w"), ensure_ascii=False, indent=2)
PYJ
say "✓ карточка «Агент по договорам» в реестре"

if ! nc -z 127.0.0.1 "$PORT" 2>/dev/null; then
  ( cd "$DST" && nohup "$PY" server.py >/tmp/extella_contract_agent.log 2>&1 & )
  sleep 2
  nc -z 127.0.0.1 "$PORT" 2>/dev/null && say "✓ сервер на :$PORT" || say "~ поднимется при открытии карточки"
fi
