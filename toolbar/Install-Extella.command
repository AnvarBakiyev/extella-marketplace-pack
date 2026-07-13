#!/bin/bash
cd "$(dirname "$0")"
echo "=== Extella: установка тулбара + Визарда ==="
echo
read -rp "Вставь свой Extella-токен и нажми Enter: " T
[ -z "$T" ] && { echo "Токен пуст."; read -n1 -rsp "Клавиша для выхода..."; exit 1; }
EXTELLA_TOKEN="$T" bash <(curl -fsSL https://raw.githubusercontent.com/AnvarBakiyev/extella-marketplace-pack/main/toolbar/install-all.sh)
echo
echo "Готово. Открой Extella → Plugins."
read -n1 -rsp "Клавиша для выхода..."
