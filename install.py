#!/usr/bin/env python3
"""Прямой установщик Extella Marketplace — регистрирует все способности в аккаунт пользователя.

Запуск ИЗ каталога репозитория:  python3 install.py

Ставит эксперты (global, cspl=fython), концепты и правила НАПРЯМУЮ через API — без агента,
поэтому НЕ упирается в лимит 50 шагов кнопки «Add GitHub Resource» на больших репозиториях.
Токен берёт из ~/extella_wizard/app/config.json; если файла нет — спросит и создаст.
Секреты не печатает. Витрину (toolbar.js) ставит отдельный ./install_toolbar.sh."""
import json, os, re, sys, glob, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.expanduser("~/extella_wizard/app/config.json")


def load_or_prompt():
    if os.path.exists(CFG_PATH):
        try:
            cfg = json.load(open(CFG_PATH, encoding="utf-8"))
            if cfg.get("auth_token"):
                return cfg
        except Exception:
            pass
    print("Нужен твой токен Extella (с api.extella.ai). Секрет никуда не печатается.")
    tok = input("Вставь Extella-токен: ").strip()
    if not tok:
        print("Токен не введён — выход."); sys.exit(1)
    cfg = {"auth_token": tok, "api_base": "https://api.extella.ai", "agent_id": "agent_extella_default"}
    os.makedirs(os.path.dirname(CFG_PATH), exist_ok=True)
    json.dump(cfg, open(CFG_PATH, "w", encoding="utf-8"))
    print("Токен сохранён:", CFG_PATH)
    return cfg


cfg = load_or_prompt()
TOKEN = cfg.get("auth_token", "")
BASE = cfg.get("api_base", "https://api.extella.ai")
HDR = {"X-Auth-Token": TOKEN, "Content-Type": "application/json",
       "X-Profile-Id": "default", "X-Agent-Id": cfg.get("agent_id", "agent_extella_default")}
if not TOKEN:
    print("В config.json нет auth_token."); sys.exit(1)


def api(path, payload, timeout=120):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode("utf-8"), headers=HDR, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def desc_of(src):
    for line in src.splitlines()[:6]:
        if line.startswith("# description:"):
            return line.split(":", 1)[1].strip()
    return ""


# ---- 1. Эксперты (главное — иначе "Expert not found" за кнопками витрины) ----
print("== Эксперты ==")
files = sorted(glob.glob(os.path.join(HERE, "experts", "*.py")))
ok = fail = 0
for i, f in enumerate(files, 1):
    name = os.path.basename(f)[:-3]
    src = open(f, encoding="utf-8").read()
    print("  [%d/%d] %s" % (i, len(files), name), flush=True)
    try:
        r = api("/api/expert/save", {"name": name, "description": desc_of(src) or name,
                                     "code": src, "kwargs": {}, "cspl": "fython", "global": True}, timeout=45)
        good = (r.get("status") == "success")
        ok += 1 if good else 0; fail += 0 if good else 1
        if not good:
            print("  ❌", name, "—", str(r)[:70])
    except Exception as e:
        print("  ❌", name, "—", str(e)[:70]); fail += 1
print("  сохранено %d / %d, ошибок %d" % (ok, len(files), fail))

# ---- 2. Концепты (best-effort; для семантического поиска) ----
print("== Концепты ==")
for f in sorted(glob.glob(os.path.join(HERE, "concepts", "*.md"))):
    if os.path.basename(f).startswith("README"):
        continue
    body = "\n".join(l for l in open(f, encoding="utf-8").read().splitlines()
                     if not l.startswith("# concept:")).strip()
    if not body:
        continue
    try:
        api("/api/concept/add", {"text": body[:6000], "global": True}); print("  ✅", os.path.basename(f))
    except Exception as e:
        print("  ⚠️", os.path.basename(f), "—", str(e)[:60])

# ---- 3. Правила (блоки "## rule:") ----
print("== Правила ==")
for f in sorted(glob.glob(os.path.join(HERE, "rules", "*.md"))):
    content = open(f, encoding="utf-8").read()
    for blk in re.split(r"(?m)^##\s*rule:\s*", content):
        blk = blk.strip()
        if not blk or blk.startswith("#"):
            continue
        rname, _, rest = blk.partition("\n")
        body = rest.split("\n---")[0].strip()
        if not body:
            continue
        try:
            api("/api/rules/add", {"rule": body[:2000], "global": True}); print("  ✅ rule:", rname[:40])
        except Exception as e:
            print("  ⚠️ rule", rname[:20], "—", str(e)[:60])

# ---- 4. Проверка ключевых экспертов ----
print("== Проверка ==")
try:
    lst = api("/api/experts_db/list", {})
    names = [e.get("name") or e.get("expert_name") for e in (lst.get("results") or lst.get("experts") or [])]
    for key in ["svc_currency", "kp_ask", "agent_flash_role"]:
        print("  ", key, "—", "на месте" if key in names else "НЕ НАЙДЕН")
except Exception:
    pass

print("\nГотово. Способности зарегистрированы. Витрину ставь отдельно: ./install_toolbar.sh")
