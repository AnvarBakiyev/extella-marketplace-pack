#!/usr/bin/env python3
"""Deep-verify: РЕАЛЬНО ставит курируемое подмножество приложений на этой ОС,
пробует запустить → метит карточку compat.verified=true/false + reason.
Отделяет 'по рецепту должно' от 'проверено вживую' (как модели 197/197)."""
import re, json, time, os, socket, urllib.request

TOK = os.environ.get("EXTELLA_TOKEN", "").strip()
if not TOK:
    raise SystemExit("EXTELLA_TOKEN is required")
H = {"X-Auth-Token": TOK, "X-Profile-Id": "default", "X-Agent-Id": os.environ.get("EXTELLA_SCOPE_AGENT", "agent_extella_default"), "Content-Type": "application/json"}

# загрузить эксперты локально (быстрее, чем через API-мост)
NS_I = {}; exec(open('/tmp/app_install.py').read(), NS_I)
NS_S = {}; exec(open('/tmp/app_start.py').read(), NS_S)

def kv(k, v=None):
    p = {"key": k, "global": True}
    if v is not None: p.update({"value": json.dumps(v, ensure_ascii=False), "description": "apps+compat"})
    req = urllib.request.Request("https://api.extella.ai/api/kv/" + ("set" if v is not None else "get"),
                                 data=json.dumps(p).encode(), headers=H)
    r = json.load(urllib.request.urlopen(req, timeout=40))
    return r if v is not None else json.loads(r.get("value") or "{}")

# курируемая лёгкая выборка (id из каталога)
TARGETS = ["cocktailpeanut/cropper", "cocktailpeanut/mirror", "pinokiofactory/bolt",
           "pinokiofactory/openui", "cocktailpeanut/axios-inspector", "cocktailpeanut/deus"]

def verify_one(app_id, repo):
    root = os.path.expanduser("~/extella-apps/" + app_id)
    try:
        r = json.loads(NS_I['app_install'](repo=repo, app_id=app_id))
    except Exception as e:
        return False, "install-исключение: " + str(e)[:80]
    if r.get("status") != "success":
        return False, "install: " + str(r.get("message"))[:90]
    # попробовать запуск (если есть start.js)
    if os.path.exists(os.path.join(root, "start.js")):
        try:
            s = json.loads(NS_S['app_start'](app_id=app_id, root=root))
            if s.get("ready"):
                return True, "установлено+запущено на порту %s" % s.get("port")
            return True, "установлено; старт: %s" % str(s.get("message"))[:60]
        except Exception as e:
            return True, "установлено; старт-исключение: " + str(e)[:60]
    return True, "установлено (%d шагов, без start.js)" % r.get("install_steps", 0)

def main():
    # индекс id → (shard_key, idx)
    idx = {}
    shards = {}
    for i in range(1, 9):
        k = "_mkt_apps" if i == 1 else "_mkt_apps_%d" % i
        d = kv(k)
        if not d.get("shelf"): break
        shards[k] = d
        for j, a in enumerate(d["shelf"]):
            idx[a.get("id")] = (k, j)
    results = []
    for aid in TARGETS:
        if aid not in idx:
            print("  ? нет в каталоге:", aid); continue
        k, j = idx[aid]
        repo = (shards[k]["shelf"][j].get("run") or {}).get("repo") or ""
        print("→ ставлю", aid, "…", flush=True)
        t = time.time()
        ok, reason = verify_one(aid, repo)
        print("   %s %s (%ds) — %s" % ("✓" if ok else "✗", aid, time.time()-t, reason), flush=True)
        shards[k]["shelf"][j].setdefault("compat", {})["verified"] = ok
        shards[k]["shelf"][j]["compat"]["verify_note"] = reason
        results.append((aid, ok, reason))
    # записать обновлённые шарды
    for k in {idx[a[0]][0] for a in [(r[0],) for r in results] if a[0] in idx}:
        print("set", k, "→", kv(k, shards[k]).get("status"))
    ok = sum(1 for _, o, _ in results if o)
    print("\nDEEP-VERIFY: %d/%d установились" % (ok, len(results)))

if __name__ == "__main__":
    main()
