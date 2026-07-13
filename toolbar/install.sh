#!/usr/bin/env bash
# Установка свежего тулбара Extella (подменяет toolbar.js в установленном приложении).
set -euo pipefail
URL="https://raw.githubusercontent.com/AnvarBakiyev/extella-marketplace-pack/main/toolbar/toolbar.js"
DEST="$HOME/Library/Application Support/extella-desktop/toolbar.js"
echo "→ Extella toolbar update"
mkdir -p "$(dirname "$DEST")"
if [ -f "$DEST" ]; then cp "$DEST" "$DEST.bak.$(date +%s)"; echo "  ✓ бэкап старого сделан"; fi
curl -fsSL "$URL" -o "$DEST.tmp"
if ! grep -q "Extella Plugins" "$DEST.tmp"; then echo "  ✗ файл не прошёл проверку"; rm -f "$DEST.tmp"; exit 1; fi
mv "$DEST.tmp" "$DEST"
echo "  ✓ установлено: $DEST ($(wc -c < "$DEST") байт)"
pkill -f "Extella.app" 2>/dev/null || true; sleep 1; open -a Extella 2>/dev/null || echo "  ! перезапусти Extella вручную"
echo "✓ Готово. Открой Extella → раздел Plugins."
