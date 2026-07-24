#!/usr/bin/env bash
# «Турагентство»: заявки, предложения, документы и сообщения клиентам.
# Код раздаётся zip'ом с VPS; загрузки/договоры — только на машине пользователя.
# Эксперты ta_* глобальны на аккаунте и приезжают сами.
set -euo pipefail
VER="0.1.0-1ae37a5"
ZIP="https://files.82-115-42-21.sslip.io/extella-travel-agency-${VER}.zip"
DST="$HOME/extella-plugins/extella_travel_agency"
REG="$HOME/extella-plugins/_registry/extella_travel_agency.json"
PORT=8766
say(){ printf "  %s\n" "$*"; }

PY=""; for c in python3 python; do $c -c 'import sys;exit(0 if sys.version_info[:2]>=(3,10) else 1)' >/dev/null 2>&1 && { PY=$c; break; }; done
[ -n "$PY" ] || { say "~ Турагентство пропущено: нужен Python 3.10+"; exit 0; }

# Машина владельца: карточка есть, а нашего .version нет — основная установка.
if [ -f "$REG" ] && [ ! -f "$DST/.version" ]; then
  say "✓ Турагентство: основная установка уже есть — не трогаю"; exit 0
fi

if [ -f "$DST/.version" ] && [ "$(cat "$DST/.version")" = "$VER" ] && [ -f "$REG" ]; then
  say "✓ Турагентство ${VER} уже установлено"; exit 0
fi

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
curl -fsSL "$ZIP" -o "$TMP/ta.zip"
mkdir -p "$DST"
unzip -qo "$TMP/ta.zip" -d "$DST"
echo "$VER" > "$DST/.version"
say "✓ код Турагентства → $DST"

mkdir -p "$HOME/extella-plugins/_registry"
# Явная (пере)установка снимает user-тумбстоун — иначе синк сочтёт карточку удалённой
rm -f "$HOME/extella-plugins/_registry/_removed/extella_travel_agency.json"
"$PY" - "$REG" "$DST" "$PORT" <<'PYJ'
import json, sys
reg, dst, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
card = {
  "id": "extella_travel_agency",
  "name": "Турагентство",
  "tagline": "Заявки, предложения, документы и сообщения клиентам",
  "description": "Пак «Турагентство»: заявки клиентов, подбор и предложения, документы и переписка в одном месте. Эксперты ta_* аккаунта уже подключены. Живой поиск туров (Tourvisor) заработает после свежего ключа от владельца — установка этим не блокируется.",
  "category": "travel", "type": "custom", "version": "0.1.0", "mode": "repo_ui",
  "ui": {"type": "local_server", "port": port, "rootPath": dst,
         "startExpert": "_etb_srv_extella_travel_agency",
         "mainFile": "index.html", "openInBrowser": False, "expectsHealth": False},
  "service": {"isApp": True, "port": port,
              "startExpert": "_etb_srv_extella_travel_agency",
              "launchCmd": "%s/server.py (python3)" % dst, "ready": True},
}
json.dump(card, open(reg, "w"), ensure_ascii=False, indent=2)
PYJ
say "✓ карточка «Турагентство» в реестре"

if ! nc -z 127.0.0.1 "$PORT" 2>/dev/null; then
  ( cd "$DST" && nohup "$PY" server.py >/tmp/extella_travel_agency.log 2>&1 & )
  sleep 2
  nc -z 127.0.0.1 "$PORT" 2>/dev/null && say "✓ сервер на :$PORT" || say "~ поднимется при открытии карточки"
fi
