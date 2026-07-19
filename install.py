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
    cfg = {"auth_token": tok, "api_base": "https://api.extella.ai",
           "agent_id": os.environ.get("EXTELLA_AGENT_ID") or "agent_extella_alibaba_default"}
    os.makedirs(os.path.dirname(CFG_PATH), exist_ok=True)
    json.dump(cfg, open(CFG_PATH, "w", encoding="utf-8"))
    print("Токен сохранён:", CFG_PATH)
    return cfg


cfg = load_or_prompt()
TOKEN = cfg.get("auth_token", "")
BASE = cfg.get("api_base", "https://api.extella.ai")
HDR = {"X-Auth-Token": TOKEN, "Content-Type": "application/json",
       "X-Profile-Id": "default", "X-Agent-Id": cfg.get("agent_id", "agent_extella_alibaba_default")}
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

# ---- 1b. Платформенные эксперты (platform_experts/): СТАВИМ, НО НЕ ЗАТИРАЕМ ----
# mcp_call/mcp_connect/mcp_list живут на платформе и правятся там же; слепая
# перезапись убила бы чужие правки — поэтому они лежат вне experts/. Но тогда
# они не создавались НИ У КОГО, и весь MCP-контур у нового клиента упирался в
# «Expert not found» (находка Wizard-чата). Семантика: создать, если нет;
# если уже есть — не трогать. ВАЖНО: платформа на отсутствующий эксперт отдаёт
# HTTP 500, а не 404 — «нет» определяем по любой неудаче чтения, не по коду.
print("== Платформенные эксперты (создать, если нет) ==")
pfiles = sorted(glob.glob(os.path.join(HERE, "platform_experts", "*.py")))
for f in pfiles:
    name = os.path.basename(f)[:-3]
    try:
        cur = api("/api/expert/get", {"name": name, "global": True}, timeout=30)
    except Exception:
        cur = {}
    if isinstance(cur, dict) and cur.get("status") == "success" and (cur.get("expert_code") or "").strip():
        print("  ⏭  %s — уже есть, не трогаю" % name)
        continue
    src = open(f, encoding="utf-8").read()
    try:
        r = api("/api/expert/save", {"name": name, "description": desc_of(src) or name,
                                     "code": src, "kwargs": {}, "cspl": "fython", "global": True}, timeout=45)
        print(("  ✅ " if r.get("status") == "success" else "  ❌ ") + name)
    except Exception as e:
        print("  ❌", name, "—", str(e)[:70])

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

# ---- composer:catalog (библиотека блоков для "Собрать") ----
cc = os.path.join(HERE, "composer_catalog.json")
if os.path.exists(cc):
    try:
        api("/api/kv/set", {"key": "composer:catalog", "value": open(cc, encoding="utf-8").read(),
                            "description": "composer catalog", "global": True})
        print("== composer:catalog ==\n  \u2705 засеян")
    except Exception as e:
        print("  \u26a0\ufe0f composer:catalog:", str(e)[:60])

# ---- _mkt_models (verified-каталог витрины: пред-проверен, шардирован; клиент видит только рабочее) ----
mc = os.path.join(HERE, "models_catalog.json")
if os.path.exists(mc):
    try:
        cat = json.load(open(mc, encoding="utf-8"))
        n = 0
        for key, shard in cat.items():  # _mkt_models, _mkt_models_2, ...
            api("/api/kv/set", {"key": key, "value": json.dumps(shard, ensure_ascii=False),
                                "description": "verified models catalog", "global": True})
            n += len(shard.get("shelf", []))
        print("== Каталог моделей ==\n  ✅ засеян verified-каталог: %d моделей" % n)
    except Exception as e:
        print("  ⚠️ _mkt_models:", str(e)[:60])

# ---- _mkt_mcp (verified-каталог MCP-серверов: npm/pypi проверены; шардирован) ----
mcp = os.path.join(HERE, "mcp_catalog.json")
if os.path.exists(mcp):
    try:
        cat = json.load(open(mcp, encoding="utf-8"))
        n = 0
        for key, shard in cat.items():  # _mkt_mcp, _mkt_mcp_2, ...
            api("/api/kv/set", {"key": key, "value": json.dumps(shard, ensure_ascii=False),
                                "description": "verified MCP catalog", "global": True})
            n += len(shard.get("shelf") or shard.get("items") or [])
        print("== Каталог MCP ==\n  ✅ засеян verified-каталог: %d серверов" % n)
    except Exception as e:
        print("  ⚠️ _mkt_mcp:", str(e)[:60])

# ---- _mkt_apps (директория приложений Pinokio-совместимых рецептов: рекламируем репо, ставит recipe_run) ----
ap = os.path.join(HERE, "apps_catalog.json")
if os.path.exists(ap):
    try:
        cat = json.load(open(ap, encoding="utf-8"))
        n = 0
        for key, shard in cat.items():
            api("/api/kv/set", {"key": key, "value": json.dumps(shard, ensure_ascii=False),
                                "description": "apps directory (recipe-installable)", "global": True})
            n += len(shard.get("shelf") or [])
        print("== Каталог приложений ==\n  ✅ засеян: %d приложений (рецепты)" % n)
    except Exception as e:
        print("  ⚠️ _mkt_apps:", str(e)[:60])

# ---- 5. Автоматизации (готовые паки: Travel Agency, Контракты, Competitor Intelligence) ----
AUTO = os.path.join(HERE, "automations")
AGENT_ID = os.environ.get("EXTELLA_AGENT_ID") or cfg.get("agent_id") or "agent_extella_alibaba_default"
if AGENT_ID == "agent_extella_default":          # никогда не ставим платного Claude клиентам
    AGENT_ID = "agent_extella_alibaba_default"
if os.path.isdir(AUTO):
    import shutil
    print("== Автоматизации ==")
    # 5a. эксперты паков (подстановка Qwen-агента коллеги вместо сентинела)
    afiles = sorted(glob.glob(os.path.join(AUTO, "experts", "*.py")))
    aok = 0
    for f in afiles:
        name = os.path.basename(f)[:-3]
        src = open(f, encoding="utf-8").read().replace("__EXTELLA_AGENT__", AGENT_ID)
        try:
            r = api("/api/expert/save", {"name": name, "description": desc_of(src) or name,
                                         "code": src, "kwargs": {}, "cspl": "fython", "global": True}, timeout=45)
            if r.get("status") == "success":
                aok += 1
            else:
                print("  ❌", name, "—", str(r)[:60])
        except Exception as e:
            print("  ❌", name, "—", str(e)[:60])
    print("  эксперты паков: %d / %d" % (aok, len(afiles)))
    # 5b. UI-папки плагинов -> ~/extella-plugins/<id>/
    PLUG = os.path.expanduser("~/extella-plugins")
    REGDIR = os.path.join(PLUG, "_registry")
    os.makedirs(REGDIR, exist_ok=True)
    uidir = os.path.join(AUTO, "ui")
    if os.path.isdir(uidir):
        for pid in os.listdir(uidir):
            sdir = os.path.join(uidir, pid)
            if not os.path.isdir(sdir):
                continue
            ddir = os.path.join(PLUG, pid)
            os.makedirs(ddir, exist_ok=True)
            for fn in os.listdir(sdir):
                try:
                    shutil.copy(os.path.join(sdir, fn), os.path.join(ddir, fn))
                except Exception:
                    pass
    # 5c. реестры плагинов (подстановка агента + правильный путь реестра под дом коллеги)
    for rf in sorted(glob.glob(os.path.join(AUTO, "registries", "*.json"))):
        raw = open(rf, encoding="utf-8").read().replace("__EXTELLA_AGENT__", AGENT_ID)
        try:
            d = json.loads(raw)
        except Exception as e:
            print("  ⚠️ реестр", os.path.basename(rf), "—", str(e)[:50]); continue
        pid = d.get("id") or os.path.basename(rf)[:-5]
        art = d.get("artifacts")
        if isinstance(art, dict):
            art["registryFile"] = os.path.join(REGDIR, pid + ".json")
        json.dump(d, open(os.path.join(REGDIR, pid + ".json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print("  ✅ пак:", d.get("name") or pid)
    # 5d. agent_id в конфиг паков, чтобы LLM-звонки шли на Qwen коллеги (не на дефолт)
    for ck in ("ta:config",):
        try:
            cur = {}
            try:
                cur = json.loads(api("/api/kv/get", {"key": ck, "global": True}).get("value") or "{}")
            except Exception:
                pass
            if not isinstance(cur, dict):
                cur = {}
            cur.setdefault("agent_id", AGENT_ID)
            api("/api/kv/set", {"key": ck, "value": json.dumps(cur, ensure_ascii=False),
                                "description": "pack config", "global": True})
        except Exception:
            pass

print("\nГотово. Способности и автоматизации зарегистрированы. Витрину ставь отдельно: ./install_toolbar.sh")
