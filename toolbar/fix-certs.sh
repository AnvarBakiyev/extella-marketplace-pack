#!/usr/bin/env bash
# Быстрый фикс SSL-сертификатов для python.org-Python на macOS (без переустановки).
set -e
PY=""; for c in python3 python; do $c -c 'import sys;exit(0 if sys.version_info[0]==3 else 1)' >/dev/null 2>&1 && { PY=$c; break; }; done
[ -z "$PY" ] && { echo "Нет Python 3"; exit 1; }
echo "Python: $($PY -V 2>&1)"
"$PY" -m pip install --quiet --disable-pip-version-check certifi >/dev/null 2>&1 || true
"$PY" - <<'P'
import os, ssl, certifi
cf = ssl.get_default_verify_paths().openssl_cafile
d = os.path.dirname(cf)
try:
    if d and not os.path.isdir(d): os.makedirs(d, exist_ok=True)
    try: os.remove(cf)
    except FileNotFoundError: pass
    os.symlink(certifi.where(), cf)
    print("✓ CA-сертификаты привязаны:", cf)
except PermissionError:
    print("✗ НЕТ ПРАВ на:", cf, "(напиши Анвару — сделаем иначе)")
except Exception as e:
    print("✗", e)
P
pkill -f "extella_wizard/app/server.py" 2>/dev/null || true
[ -f "$HOME/extella_wizard/app/server.py" ] && ( cd "$HOME/extella_wizard/app" && nohup "$PY" server.py >/tmp/wz.log 2>&1 & )
pkill -f "Extella.app" 2>/dev/null || true; sleep 1; open -a Extella 2>/dev/null || true
echo "Готово. Открой Extella → Plugins → Визард."
