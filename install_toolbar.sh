#!/bin/bash
# Ставит витрину (toolbar.js) в Extella Desktop + при необходимости заводит токен.
# Пре-собранный toolbar.js — сборка не нужна.
set -e
OS=$(uname -s)
if [ "$OS" = "Darwin" ]; then TB="$HOME/Library/Application Support/extella-desktop"; else TB="$HOME/.config/extella-desktop"; fi
mkdir -p "$TB"
[ -f "$TB/toolbar.js" ] && cp "$TB/toolbar.js" "$TB/toolbar.js.bak.$(date +%s)" && echo "  бэкап старого toolbar.js создан"
cp "$(cd "$(dirname "$0")" && pwd)/toolbar/toolbar.js" "$TB/toolbar.js"
echo "✓ Витрина установлена: $TB/toolbar.js"

# Токен для экспертов, которые сами зовут API (kp_ask — ответы по базе знаний, agent_flash_role — прошивка ролей).
# Создаём config.json ТОЛЬКО если его ещё нет — чтобы не затереть настройку «Визарда внедрения», если он уже стоит.
CFG="$HOME/extella_wizard/app/config.json"
if [ -f "$CFG" ]; then
  echo "✓ Токен уже настроен ($CFG) — пропускаю."
else
  echo ""
  echo "  Для ответов по базам знаний и прошивки ролей нужен твой токен Extella (с api.extella.ai)."
  read -p "  Вставь Extella-токен (или Enter, чтобы пропустить): " EXT_TOKEN
  if [ -n "$EXT_TOKEN" ]; then
    mkdir -p "$HOME/extella_wizard/app"
    cat > "$CFG" <<JSON
{"auth_token": "$EXT_TOKEN", "api_base": "https://api.extella.ai", "agent_id": "agent_extella_default"}
JSON
    echo "✓ Токен сохранён: $CFG"
  else
    echo "  ⚠ Пропущено. Витрина, живые сервисы и CLI работают; ответы по базе знаний и прошивка ролей — после добавления токена."
  fi
fi
echo ""
echo "  Перезапусти Extella Desktop (Cmd+Q → открыть заново) — витрина появится сверху."
echo "  Затем направь Extella на этот репозиторий, чтобы зарегистрировать способности (см. README)."
