#!/usr/bin/env bash
# Плагин «Подключения» (Connectors hub): каждый пользователь подключает СВОИ сервисы/CRM/кабинеты.
# Код раздаётся zip'ом с VPS (не публичный GitHub). Секреты: у каждого свой vault (~/.extella-connectors),
# свой Composio-ключ вводится во вкладке «Мой Composio» — чужие ключи не участвуют.
set -euo pipefail
VER="0.1.0-ca5a7e2"
ZIP="https://files.82-115-42-21.sslip.io/extella-connectors-${VER}.zip"
DST="$HOME/extella-plugins/connectors"
REG="$HOME/extella-plugins/_registry/extella_connectors.json"
PORT=34794
say(){ printf "  %s\n" "$*"; }

PY=""; for c in python3 python; do $c -c 'import sys;exit(0 if sys.version_info[:2]>=(3,10) else 1)' >/dev/null 2>&1 && { PY=$c; break; }; done
[ -n "$PY" ] || { say "~ Connectors пропущен: нужен Python 3.10+"; exit 0; }

# Идемпотентность: та же версия уже стоит — не трогаем (state в ~/.extella-connectors не задет в любом случае)
if [ -f "$DST/.version" ] && [ "$(cat "$DST/.version")" = "$VER" ] && [ -f "$REG" ]; then
  say "✓ Connectors ${VER} уже установлен"; exit 0
fi

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
curl -fsSL "$ZIP" -o "$TMP/c.zip"
unzip -q "$TMP/c.zip" -d "$TMP/src"
mkdir -p "$DST"
# Код заменяем целиком; .venv и .version живут рядом и переживают обновление кода
find "$DST" -mindepth 1 -maxdepth 1 ! -name ".venv" ! -name ".version" -exec rm -rf {} +
cp -R "$TMP/src/." "$DST/"

if [ ! -x "$DST/.venv/bin/python3" ]; then
  "$PY" -m venv "$DST/.venv"
fi
"$DST/.venv/bin/pip" install --quiet --disable-pip-version-check "$DST" \
  && say "✓ ядро Connectors" || { say "✗ pip install не прошёл"; exit 0; }
"$DST/.venv/bin/pip" install --quiet --disable-pip-version-check "composio==0.17.1" \
  && say "✓ Composio SDK" || say "~ Composio SDK не встал (хаб работает; каталог оживёт после установки SDK)"
echo "$VER" > "$DST/.version"

mkdir -p "$HOME/extella-plugins/_registry"
"$PY" - "$REG" "$DST" "$PORT" <<'PYJ'
import json, sys
reg, dst, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
card = {
  "id": "extella_connectors",
  "title": "Подключения",
  "subtitle": "Свои сервисы, CRM и кабинеты — один контур доступа",
  "ui": {"type": "local_server", "port": port, "rootPath": dst,
          "mainFile": "ui/index.html", "openInBrowser": False, "expectsHealth": True},
  "service": {"port": port,
      "launchCmd": "PYTHONPATH=%s/src %s/.venv/bin/python3 -m extella_connectors.server --state-root $HOME/.extella-connectors --port %d" % (dst, dst, port)}
}
json.dump(card, open(reg, "w"), ensure_ascii=False, indent=2)
PYJ
say "✓ карточка «Подключения» в реестре"

# мягкий старт сейчас (автоподъём при ребуте делает ai.extella.local-servers)
if [ "${EXTELLA_CONNECTORS_NO_START:-}" = "" ] && ! nc -z 127.0.0.1 "$PORT" 2>/dev/null; then
  ( cd "$DST" && PYTHONPATH="$DST/src" nohup "$DST/.venv/bin/python3" -m extella_connectors.server \
      --state-root "$HOME/.extella-connectors" --port "$PORT" >/tmp/extella_connectors.log 2>&1 & )
  sleep 2
  nc -z 127.0.0.1 "$PORT" 2>/dev/null && say "✓ хаб на :$PORT" || say "~ хаб поднимется при открытии карточки"
fi
