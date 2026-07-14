# expert: wz_self_update
# description: Обновляет Extella из GitHub одной кнопкой: качает свежий toolbar.js в папку Electron + прогоняет install.py пака (эксперты+каталоги) под токеном аккаунта. Возвращает {status, toolbar_updated, seeded, message}. После — перезапустить Extella (Cmd+Q).
def wz_self_update(what="all"):
    import os, sys, json, ssl, tarfile, tempfile, subprocess, urllib.request
    RAW = "https://raw.githubusercontent.com/AnvarBakiyev/extella-marketplace-pack/main/toolbar/toolbar.js"
    TARBALL = "https://github.com/AnvarBakiyev/extella-marketplace-pack/archive/refs/heads/main.tar.gz"
    res = {"status": "success", "toolbar_updated": False, "seeded": False, "message": ""}
    ctx = ssl.create_default_context()
    try:
        import certifi; ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception: pass

    def _dl(url, timeout=120):
        req = urllib.request.Request(url, headers={"User-Agent": "extella-updater"})
        return urllib.request.urlopen(req, timeout=timeout, context=ctx).read()

    # 1. свежий toolbar.js → папка Electron (по ОС)
    if what in ("all", "toolbar"):
        home = os.path.expanduser("~")
        cands = [
            os.path.join(home, "Library/Application Support/extella-desktop/toolbar.js"),        # macOS
            os.path.join(os.environ.get("APPDATA", ""), "extella-desktop", "toolbar.js"),         # Windows
            os.path.join(home, ".config/extella-desktop/toolbar.js"),                             # Linux
        ]
        target = next((p for p in cands if p and os.path.isdir(os.path.dirname(p))), None)
        if target:
            try:
                data = _dl(RAW)
                if b"Extella Plugins" in data or b"renderApps" in data:   # sanity: это наш toolbar
                    if os.path.exists(target):
                        try: open(target + ".bak", "wb").write(open(target, "rb").read())
                        except Exception: pass
                    open(target, "wb").write(data)
                    res["toolbar_updated"] = True
                else:
                    res["message"] += "toolbar.js не прошёл проверку; "
            except Exception as e:
                res["message"] += "toolbar: " + str(e)[:60] + "; "
        else:
            res["message"] += "папка Extella не найдена; "

    # 2. эксперты + каталоги: скачать пак-тарбол → install.py (использует config.json аккаунта)
    if what in ("all", "server"):
        try:
            tmp = tempfile.mkdtemp(prefix="extella_upd_")
            tgz = os.path.join(tmp, "pack.tgz")
            open(tgz, "wb").write(_dl(TARBALL, timeout=180))
            with tarfile.open(tgz) as tf: tf.extractall(tmp)
            pack = next((os.path.join(tmp, d) for d in os.listdir(tmp)
                         if d.startswith("extella-marketplace-pack") and os.path.isdir(os.path.join(tmp, d))), None)
            if pack and os.path.exists(os.path.join(pack, "install.py")):
                py = sys.executable
                r = subprocess.run([py, "install.py"], cwd=pack, capture_output=True, text=True, timeout=600)
                res["seeded"] = (r.returncode == 0)
                tail = (r.stdout or "").strip().splitlines()[-3:] if r.stdout else []
                res["message"] += ("эксперты/каталоги обновлены; " if res["seeded"] else ("install.py: " + " ".join(tail)[-100:] + "; "))
            else:
                res["message"] += "install.py в паке не найден; "
        except Exception as e:
            res["message"] += "server: " + str(e)[:60] + "; "

    ok = res["toolbar_updated"] or res["seeded"]
    res["status"] = "success" if ok else "error"
    res["message"] = ("✓ Обновлено. Перезапусти Extella (Cmd+Q) — увидишь свежий интерфейс. " + res["message"]) if ok \
        else ("Не удалось обновить: " + res["message"])
    return json.dumps(res, ensure_ascii=False)
