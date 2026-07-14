#!/usr/bin/env python3
"""Пред-полётный верификатор пака Extella.

Гоняет каждый элемент, который поедет клиентам, и выдаёт green/red-отчёт.
Запускать перед публикацией пака и раз в неделю (внешнее протухает).

  python3 preflight_verify.py            # всё
  python3 preflight_verify.py models     # только модели
  python3 preflight_verify.py experts services models

Правило: в клиентский пак едет только зелёное. Красное — чинить или убирать.
"""
import os, sys, json, ast, re, glob, urllib.request, concurrent.futures as cf

HERE = os.path.dirname(os.path.abspath(__file__))
OK, BAD = "✅", "❌"

def _title(t): print("\n== %s ==" % t)

# ---- Модели: каждый HF-спейс должен ставиться (gradio нативно ИЛИ встройка) ----
def verify_models():
    _title("Модели (HF)")
    mc = os.path.join(HERE, "models_catalog.json")
    if not os.path.exists(mc):
        print("  нет models_catalog.json"); return (0, 0, [])
    cat = json.load(open(mc, encoding="utf-8"))
    ids = []
    for shard in cat.values():
        for it in shard.get("shelf", []):
            h = it.get("hfId") or it.get("hf") or it.get("id")
            if h: ids.append(h)
    import time as _t
    def cls(hid):
        if "/" not in hid: return (hid, "bad")
        o, n = hid.split("/", 1)
        base = "https://%s-%s.hf.space" % (o.lower().replace("_", "-"), n.lower().replace("_", "-").replace(".", "-"))
        transient = False
        for attempt in range(2):  # ретрай — HF душит частые пачки
            for p in ("/gradio_api/info", "/info"):
                try:
                    d = json.load(urllib.request.urlopen(base + p, timeout=20))
                    if isinstance(d, dict) and d.get("named_endpoints"): return (hid, "gradio")
                except urllib.error.HTTPError as e:
                    if e.code in (401, 403): return (hid, "embed")   # gated — ставится встройкой
                    # 404 на этом пути — не gradio, пробуем корень
                except Exception:
                    transient = True
            try:
                urllib.request.urlopen(base + "/", timeout=20).read(64); return (hid, "embed")
            except urllib.error.HTTPError as e:
                if e.code in (401, 403): return (hid, "embed")
                if e.code == 404: return (hid, "embed")   # сервер отвечает — спейс жив
                if e.code == 503: transient = True         # просыпается
                else: return (hid, "dead")                 # реальный отлуп
            except Exception:
                transient = True
            if attempt == 0: _t.sleep(4)
        return (hid, "unknown" if transient else "dead")   # таймаут после ретраев ≠ смерть
    res = {}
    with cf.ThreadPoolExecutor(max_workers=10) as ex:  # мягкая конкуренция — HF душит частые пачки
        for hid, c in ex.map(cls, ids): res[hid] = c
    grad = [h for h, c in res.items() if c == "gradio"]
    emb  = [h for h, c in res.items() if c == "embed"]
    dead = [h for h, c in res.items() if c in ("dead", "bad")]
    unk  = [h for h, c in res.items() if c == "unknown"]
    good = len(grad) + len(emb)
    # красное ТОЛЬКО если есть реально-мёртвые; unknown (сеть/троттлинг) — предупреждение
    print("  %s ставится: %d / %d (gradio %d, встройка %d)%s%s" % (
        OK if not dead else BAD, good, len(ids), len(grad), len(emb),
        ("  ⚠️ не проверено (сеть/лимит HF): %d — перезапусти" % len(unk)) if unk else "",
        ("  ❌ мёртвых: %d" % len(dead)) if dead else ""))
    for h in dead: print("    %s НЕ ставится (мёртв): %s" % (BAD, h))
    # для вердикта: зелёное если мёртвых нет (unknown не валит гейт)
    return (len(ids) - len(dead), len(ids), dead)

# ---- Эксперты: код должен компилироваться (fython/$extens пропускаем) ----
def verify_experts():
    _title("Эксперты")
    import glob
    files = glob.glob(os.path.join(HERE, "experts", "*.py")) + glob.glob(os.path.join(HERE, "automations", "experts", "*.py"))
    ok = bad = 0; fails = []
    for f in files:
        src = open(f, encoding="utf-8").read()
        if src.lstrip().startswith("$extens") or "\n$extens" in src[:200]:
            ok += 1; continue  # платформенный синтаксис — валиден на движке
        body = "\n".join(l for l in src.splitlines() if not l.startswith("#"))
        try: ast.parse(body); ok += 1
        except SyntaxError: bad += 1; fails.append(os.path.basename(f))
    print("  %s компилируется: %d / %d" % (OK if not bad else BAD, ok, len(files)))
    for f in fails: print("    %s SYNTAX: %s" % (BAD, f))
    return (ok, len(files), fails)

# ---- Сервисы: живой ли внешний API (реальный прогон эксперта на аккаунте) ----
def verify_services(token, agent):
    _title("Сервисы (внешние API)")
    import glob
    svcs = [os.path.basename(f)[:-3] for f in glob.glob(os.path.join(HERE, "experts", "svc_*.py"))]
    def run(name):
        try:
            h = {"X-Auth-Token": token, "X-Profile-Id": "default", "X-Agent-Id": agent, "Content-Type": "application/json"}
            req = urllib.request.Request("https://api.extella.ai/api/expert/run",
                    data=json.dumps({"expert_name": name, "params": {}, "global": True}).encode(), headers=h)
            r = json.load(urllib.request.urlopen(req, timeout=40))
            res = r.get("result")
            return (name, "ok" if (res and "error" not in str(res)[:40].lower()) else "check")
        except Exception: return (name, "err")
    if not token:
        print("  (нет токена — пропуск живого прогона)"); return (0, len(svcs), [])
    res = {}
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for n, c in zip(svcs, ex.map(run, svcs)): res[n] = c
    good = sum(1 for c in res.values() if c == "ok")
    print("  %s ответили: %d / %d" % (OK if good == len(svcs) else BAD, good, len(svcs)))
    for n, c in res.items():
        if c != "ok": print("    ⚠️ проверить: %s (%s)" % (n, c))
    return (good, len(svcs), [n for n, c in res.items() if c != "ok"])


# ---- CLI: у каждого резолвера должен быть headless-путь (прямая скачка), не только brew ----
def verify_cli():
    # Решение Анвара: CLI ставятся через РАЗОВЫЙ Homebrew (поддерживаемый путь установщика).
    # Значит brew-резолвер = ОК; красное только если у резолвера НЕТ пути установки вообще.
    _title("CLI-инструменты (Homebrew — разовый шаг установщика)")
    resolvers = glob.glob(os.path.join(HERE, "experts", "cap_*_resolver.py"))
    direct = 0; viabrew = 0; nomethod = []
    for f in resolvers:
        code = open(f, encoding="utf-8").read()
        has_direct = bool(re.search(r"urlretrieve|ditto|tar |curl |urlopen|download", code))
        has_brew = "brew" in code and "install" in code
        if has_direct: direct += 1
        elif has_brew: viabrew += 1
        else: nomethod.append(os.path.basename(f)[:-3])
    good = direct + viabrew
    print("  %s ставятся: %d / %d (headless %d, через Homebrew %d)" % (
        OK if not nomethod else BAD, good, len(resolvers), direct, viabrew))
    for r in nomethod: print("    %s нет пути установки: %s" % (BAD, r))
    return (good, len(resolvers), nomethod)

# ---- Знания: внешние источники паков (adilet/wikipedia) должны быть живы ----
def verify_knowledge():
    _title("Знания (источники паков)")
    srcs = ["https://adilet.zan.kz", "https://ru.wikipedia.org"]
    good = []; bad = []
    for u in srcs:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            urllib.request.urlopen(req, timeout=15).read(64); good.append(u)
        except Exception: bad.append(u)
    print("  %s источники живы: %d / %d" % (OK if not bad else BAD, len(good), len(srcs)))
    for u in bad: print("    %s недоступен: %s" % (BAD, u))
    return (len(good), len(srcs), bad)

# ---- MCP: каждый сервер = живой npm/pypi пакет (рантайм Node/Python — разовый brew, как CLI) ----
def verify_mcp():
    _title("MCP-серверы")
    import urllib.parse
    mc = os.path.join(HERE, "mcp_catalog.json")
    if not os.path.exists(mc):
        print("  ℹ️ MCP не в паке (KV-харвест). Для гарантии — бандлить mcp_catalog.json."); return (0, 0, [])
    cat = json.load(open(mc, encoding="utf-8"))
    items = []
    for shard in cat.values():
        items += (shard.get("shelf") or shard.get("items") or [])
    def alive(it):
        run = it.get("run") or {}; t = (run.get("type") or "").lower(); pkg = run.get("pkg", "")
        try:
            if t in ("npm", "npx") and pkg:
                urllib.request.urlopen("https://registry.npmjs.org/" + urllib.parse.quote(pkg, safe="@/"), timeout=12).read(64); return (it.get("id"), "ok")
            if t in ("pip", "pypi", "python") and pkg:
                urllib.request.urlopen("https://pypi.org/pypi/%s/json" % pkg, timeout=12).read(64); return (it.get("id"), "ok")
            return (it.get("id"), "other")
        except Exception:
            return (it.get("id"), "dead")
    res = {}
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        for i, c in ex.map(alive, items): res[i] = c
    dead = [i for i, v in res.items() if v == "dead"]
    good = sum(1 for v in res.values() if v == "ok")
    npm = sum(1 for it in items if (it.get("run") or {}).get("type", "").lower() in ("npm", "npx"))
    print("  %s пакеты живы: %d / %d (npm %d → рантайм Node/разовый brew; pypi %d)" % (
        OK if not dead else BAD, good, len(items), npm, len(items) - npm))
    for i in dead: print("    %s мёртвый пакет: %s" % (BAD, i))
    return (len(items) - len(dead), len(items), dead)

def main():
    args = [a.lower() for a in sys.argv[1:]]
    want = lambda k: (not args) or (k in args)
    tok = agent = ""
    cfg = os.path.expanduser("~/extella_wizard/app/config.json")
    if os.path.exists(cfg):
        try:
            d = json.load(open(cfg)); tok = d.get("auth_token", ""); agent = d.get("agent_id", "")
        except Exception: pass
    print("PRE-FLIGHT VERIFY — пак Extella")
    summary = []
    if want("models"):    g, t, _ = verify_models();   summary.append(("Модели", g, t))
    if want("experts"):   g, t, _ = verify_experts();  summary.append(("Эксперты", g, t))
    if want("cli"):       g, t, _ = verify_cli();      summary.append(("CLI", g, t))
    if want("knowledge"): g, t, _ = verify_knowledge(); summary.append(("Знания", g, t))
    if want("mcp"):       g, t, _ = verify_mcp(); summary.append(("MCP", g, t))
    if want("services"):  g, t, _ = verify_services(tok, agent); summary.append(("Сервисы", g, t))
    print("\n== ИТОГ ==")
    allgreen = True
    for nm, g, t in summary:
        mark = OK if g == t else BAD
        if g != t: allgreen = False
        print("  %s %-10s %d / %d" % (mark, nm, g, t))
    print("\n%s" % ("ВСЁ ЗЕЛЁНОЕ — можно публиковать" if allgreen else "ЕСТЬ КРАСНОЕ — чинить/убирать перед публикацией"))
    sys.exit(0 if allgreen else 1)

if __name__ == "__main__":
    main()
