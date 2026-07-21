# expert: app_uninstall
# description: Удаляет установленное приложение: останавливает запущенный процесс (по порту из лога/реестра), сносит папку ~/extella-apps/<app_id>, убирает реестр плагина. Возвращает {status, app_id, freed_mb}.
def app_uninstall(app_id="", root=""):
    import os, json, re, shutil, subprocess
    def out(**k): k.setdefault("app_id", app_id); return json.dumps(k, ensure_ascii=False)
    root = os.path.expanduser(root or ("~/extella-apps/" + (app_id or "")))
    if not app_id and not os.path.isdir(root):
        return out(status="error", message="не указан app_id")
    if not os.path.isdir(root):
        return out(status="success", message="уже удалено", removed=False)

    # размер до удаления (для отчёта)
    freed_mb = 0
    try:
        tot = 0
        for dp, _, fs in os.walk(root):
            for f in fs:
                try: tot += os.path.getsize(os.path.join(dp, f))
                except Exception: pass
        freed_mb = round(tot / 1048576)
    except Exception: pass

    # 1. остановить запущенный процесс: порт из server.log (или реестра) → убить слушателя
    ports = set()
    try:
        log = os.path.join(root, "server.log")
        if os.path.isfile(log):
            txt = open(log, encoding="utf-8", errors="ignore").read()
            for p in re.findall(r"https?://(?:127\.0\.0\.1|localhost|0\.0\.0\.0):(\d{2,5})", txt):
                ports.add(int(p))
    except Exception: pass
    registry_root = os.environ.get("EXTELLA_PLUGIN_REGISTRY") or os.path.join(
        os.environ.get("EXTELLA_PLUGIN_ROOT") or os.path.expanduser("~/extella-plugins"), "_registry"
    )
    reg_candidates = [
        os.path.join(registry_root, app_id + ".json"),
        os.path.join(registry_root, app_id.replace("/", "_") + ".json"),
        os.path.join(registry_root, re.sub(r"[^a-zA-Z0-9]", "_", app_id) + ".json"),
        os.path.join(registry_root, app_id.split("/")[-1] + ".json"),
    ]
    for reg in reg_candidates:
        try:
            if os.path.isfile(reg):
                man = json.load(open(reg, encoding="utf-8"))
                pr = (man.get("ui") or {}).get("port")
                if pr: ports.add(int(pr))
        except Exception: pass
    for pr in ports:
        try:
            pids = subprocess.run(["lsof", "-ti", "tcp:%d" % pr], capture_output=True, text=True, timeout=10).stdout.split()
            for pid in pids:
                try: subprocess.run(["kill", "-9", pid], timeout=5)
                except Exception: pass
        except Exception: pass
    # плюс best-effort: процессы, запущенные ИЗ папки приложения
    try: subprocess.run("pkill -9 -f " + re.escape(root), shell=True, timeout=10)
    except Exception: pass

    # 2. снести папку приложения
    shutil.rmtree(root, ignore_errors=True)

    # 3. убрать реестр плагина
    for reg in reg_candidates:
        try:
            if os.path.isfile(reg): os.remove(reg)
        except Exception: pass

    ok = not os.path.isdir(root)
    return out(status="success" if ok else "error", removed=ok,
               freed_mb=freed_mb, message=("удалено, освобождено ~%d МБ" % freed_mb) if ok else "не удалось полностью удалить")
