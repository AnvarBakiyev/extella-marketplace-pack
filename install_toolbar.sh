#!/bin/bash
# Ставит витрину (toolbar.js) в Extella Desktop. Пре-собранный файл — сборка не нужна.
set -e
OS=$(uname -s)
if [ "$OS" = "Darwin" ]; then TB="$HOME/Library/Application Support/extella-desktop"; else TB="$HOME/.config/extella-desktop"; fi
mkdir -p "$TB"
[ -f "$TB/toolbar.js" ] && cp "$TB/toolbar.js" "$TB/toolbar.js.bak.$(date +%s)" && echo "  бэкап старого toolbar.js создан"
cp "$(cd "$(dirname "$0")" && pwd)/toolbar/toolbar.js" "$TB/toolbar.js"
echo "✓ Витрина установлена: $TB/toolbar.js"
echo "  Перезапусти Extella Desktop (Cmd+Q → открыть заново) — витрина появится сверху."
