#!/usr/bin/env python3
"""Пред-полётный верификатор пака Extella.

Гоняет каждый элемент, который поедет клиентам, и выдаёт green/red-отчёт.
Запускать перед публикацией пака и раз в неделю (внешнее протухает).

  python3 preflight_verify.py            # всё
  python3 preflight_verify.py models     # только модели
  python3 preflight_verify.py experts services models

Правило: в клиентский пак едет только зелёное. Красное — чинить или убирать.
"""
import os, sys, json, ast, urllib.request, concurrent.futures as cf

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
    def cls(hid):
        if "/" not in hid: return (hid, "bad")
        o, n = hid.split("/", 1)
        base = "https://%s-%s.hf.space" % (o.lower().replace("_", "-"), n.lower().replace("_", "-").replace(".", "-"))
        for p in ("/gradio_api/info", "/info"):
            try:
                d = json.load(urllib.request.urlopen(base + p, timeout=15))
                if isinstance(d, dict) and d.get("named_endpoints"): return (hid, "gradio")
            except Exception: pass
        try:
            urllib.request.urlopen(base + "/", timeout=15).read(64); return (hid, "embed")
        except Exception: return (hid, "dead")
    res = {}
    with cf.ThreadPoolExecutor(max_workers=10) as ex:  # мягкая конкуренция — HF душит частые пачки
        for hid, c in ex.map(cls, ids): res[hid] = c
    grad = [h for h, c in res.items() if c == "gradio"]
    emb  = [h for h, c in res.items() if c == "embed"]
    dead = [h for h, c in res.items() if c in ("dead", "bad")]
    good = len(grad) + len(emb)               # РЕАЛЬНЫЕ проходы, не "всего минус мёртвые"
    incomplete = len(res) < len(ids)
    print("  %s ставится: %d / %d (gradio %d, встройка %d, мёртвых %d)%s" % (
        OK if (good == len(ids)) else BAD, good, len(ids), len(grad), len(emb), len(dead),
        "  ⚠️ проверка НЕПОЛНАЯ (сеть/лимит HF) — перезапусти" if incomplete else ""))
    for h in dead: print("    %s НЕ ставится (мёртв): %s" % (BAD, h))
    return (good, len(ids), dead)

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
    if want("models"):   g, t, _ = verify_models();   summary.append(("Модели", g, t))
    if want("experts"):  g, t, _ = verify_experts();  summary.append(("Эксперты", g, t))
    if want("services"): g, t, _ = verify_services(tok, agent); summary.append(("Сервисы", g, t))
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
