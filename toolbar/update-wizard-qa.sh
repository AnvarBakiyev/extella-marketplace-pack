#!/usr/bin/env bash
# Быстрое QA-обновление: только изменённые UI-файлы и платформенные артефакты визарда.
set -euo pipefail

WIZARD_REF="${EXTELLA_WIZARD_REF:-codex/prod-hardening}"
REPO="AnvarBakiyev/extella-adoption-wizard"
ARCHIVE="https://github.com/${REPO}/archive/refs/heads/${WIZARD_REF}.tar.gz"
REF_ENC=$(printf '%s' "$WIZARD_REF" | sed 's|/|%2F|g')
COMMIT_API="https://api.github.com/repos/${REPO}/commits/${REF_ENC}"
COMPARE_API="https://api.github.com/repos/${REPO}/compare"
WA="$HOME/extella_wizard/app"
STATE="$WA/.qa_revision"
# Первая QA-сборка с быстрым обновлением ещё не писала STATE. Если health=4.93, точно знаем её SHA.
BASELINE_VERSION="4.93"
BASELINE_SHA="d206066c4b6febe7b5b02cdc99ddb5fac1d1edf5"
FULL_CMD='bash <(curl -fsSL https://raw.githubusercontent.com/AnvarBakiyev/extella-marketplace-pack/codex-qa/toolbar/install-all.sh)'

say(){ printf "\n\033[1m%s\033[0m\n" "$*"; }
die_full(){ printf "\n✗ %s\nНужна полная QA-установка:\n  %s\n" "$1" "$FULL_CMD"; exit 2; }

PY=""
for c in python3 python; do
  "$c" -c 'import sys;raise SystemExit(0 if sys.version_info[0]==3 else 1)' >/dev/null 2>&1 && { PY="$c"; break; }
done
[ -n "$PY" ] || die_full "Не найден Python 3."
[ -f "$WA/config.json" ] || die_full "Визард ещё не установлен."

say "Быстрое QA-обновление Extella · ${WIZARD_REF}"
LATEST=$(curl -fsSL "$COMMIT_API" | "$PY" -c 'import json,sys; print((json.load(sys.stdin) or {}).get("sha", ""))')
[ ${#LATEST} -eq 40 ] || die_full "GitHub не вернул commit QA-ветки."

OLD="${EXTELLA_QA_FROM_SHA:-}"
if [ -z "$OLD" ] && [ -f "$STATE" ]; then OLD=$(tr -d '[:space:]' < "$STATE"); fi
if [ -z "$OLD" ]; then
  HEALTH=$(curl -fsS http://127.0.0.1:8765/x/health 2>/dev/null || true)
  CUR_VER=$(printf '%s' "$HEALTH" | "$PY" -c 'import json,sys; print((json.load(sys.stdin) or {}).get("version", ""))' 2>/dev/null || true)
  [ "$CUR_VER" = "$BASELINE_VERSION" ] || die_full "Не удалось доказать исходную QA-версию устройства."
  OLD="$BASELINE_SHA"
  echo "  исходная QA-версия: $BASELINE_VERSION"
fi
[ ${#OLD} -eq 40 ] || die_full "Повреждена локальная отметка QA-версии."

if [ "$OLD" = "$LATEST" ]; then
  printf '%s\n' "$LATEST" > "$STATE"
  echo "  ✓ уже установлена последняя QA-сборка (${LATEST:0:7})"
  exit 0
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
curl -fsSL "${COMPARE_API}/${OLD}...${LATEST}" -o "$TMP/compare.json"
STATUS=$("$PY" - "$TMP/compare.json" <<'PY'
import json,sys
try: print((json.load(open(sys.argv[1], encoding="utf-8")) or {}).get("status", ""))
except Exception: print("")
PY
)
[ "$STATUS" = "ahead" ] || die_full "QA-ветка разошлась с установленной версией ($STATUS)."

"$PY" - "$TMP/compare.json" > "$TMP/files.txt" <<'PY'
import json,sys
d=json.load(open(sys.argv[1], encoding="utf-8"))
for f in d.get("files") or []:
    name=str(f.get("filename") or "")
    if name: print(name)
PY

echo "  изменений в Git: $(wc -l < "$TMP/files.txt" | tr -d ' ')"
if [ "${EXTELLA_QA_DRY_RUN:-0}" = "1" ]; then
  sed 's/^/  · /' "$TMP/files.txt"
  echo "  ✓ dry-run: устройство не изменено"
  exit 0
fi

if ! grep -Eq '^(ui/|experts/.*\.py$|concepts/.*\.md$|rules/.*\.md$)' "$TMP/files.txt"; then
  printf '%s\n' "$LATEST" > "$STATE"
  echo "  ✓ менялись только тесты/документация — устройство уже актуально"
  exit 0
fi

curl -fsSL "$ARCHIVE" -o "$TMP/w.tgz"
tar -xzf "$TMP/w.tgz" -C "$TMP"
WD=$(find "$TMP" -maxdepth 1 -type d -name 'extella-adoption-wizard-*' | head -1)
[ -n "$WD" ] && [ -f "$WD/install.py" ] || die_full "Архив QA-ветки не распаковался."

# Платформенные сущности дороги: install.py получит только реально изменённые файлы.
"$PY" - "$TMP/files.txt" > "$TMP/runtime.txt" <<'PY'
import sys
for line in open(sys.argv[1], encoding="utf-8"):
    p=line.strip()
    if p.startswith(("experts/", "concepts/", "rules/")) and p.endswith((".py", ".md")):
        print(p)
PY
if [ -s "$TMP/runtime.txt" ]; then
  DELTA=$(paste -sd, "$TMP/runtime.txt")
  say "Изменённые эксперты/концепты"
  ( cd "$WD" && EXTELLA_DELTA_FILES="$DELTA" "$PY" install.py )
else
  echo "  ✓ эксперты и концепты не менялись"
fi

UI_CHANGED=0
if grep -q '^ui/' "$TMP/files.txt"; then UI_CHANGED=1; fi
if [ "$UI_CHANGED" -eq 1 ]; then
  say "Изменённый интерфейс"
  BACKUP="$TMP/ui-backup"
  mkdir -p "$BACKUP"
  for f in "$WA"/*.py "$WA"/wizard.html; do [ -f "$f" ] && cp "$f" "$BACKUP/"; done
  cp "$WD/ui/"*.py "$WD/ui/wizard.html" "$WA/"
  pkill -f "extella_wizard/app/server.py" 2>/dev/null || true
  ( cd "$WA" && nohup "$PY" server.py >/tmp/extella_wizard.log 2>&1 & )
  HEALTH=""
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    HEALTH=$(curl -fsS http://127.0.0.1:8765/x/health 2>/dev/null || true)
    [ -n "$HEALTH" ] && break
    sleep 0.5
  done
  if [ -z "$HEALTH" ]; then
    cp "$BACKUP/"* "$WA/"
    pkill -f "extella_wizard/app/server.py" 2>/dev/null || true
    ( cd "$WA" && nohup "$PY" server.py >/tmp/extella_wizard.log 2>&1 & )
    die_full "Новый мост не поднялся; UI автоматически возвращён."
  fi
  VER=$(printf '%s' "$HEALTH" | "$PY" -c 'import json,sys; print((json.load(sys.stdin) or {}).get("version", ""))')
  echo "  ✓ интерфейс и мост обновлены · версия $VER"
else
  echo "  ✓ UI не менялся — перезапуск не нужен"
fi

printf '%s\n' "$LATEST" > "$STATE"
echo "  ✓ QA ${OLD:0:7} → ${LATEST:0:7}"
say "Готово — обновлены только изменения"
