#!/bin/bash
cd "$(dirname "$0")"
echo "=== Extella: установка тулбара + Визарда ==="
echo
echo "Шаг 1. Токен — из приложения Extella (сгенерируй/спроси у Анвара)."
read -rp "Вставь Extella-токен и нажми Enter: " T
[ -z "$T" ] && { echo "Токен пуст."; read -n1 -rsp "Клавиша для выхода..."; exit 1; }
echo
echo "Шаг 2. id своего Qwen-агента — сделай в Extella копию базового Qwen (2 клика) и скопируй её id (начинается с agent_)."
echo "       Можно пропустить (Enter) — тогда Визард-чат работать не будет, только витрина."
read -rp "Вставь id агента (agent_...) или Enter: " A
EXTELLA_TOKEN="$T" EXTELLA_AGENT_ID="$A" bash <(curl -fsSL https://raw.githubusercontent.com/AnvarBakiyev/extella-marketplace-pack/main/toolbar/install-all.sh)
echo
echo "Готово. Открой Extella → Plugins."
read -n1 -rsp "Клавиша для выхода..."
