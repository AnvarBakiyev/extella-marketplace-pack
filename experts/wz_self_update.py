# expert: wz_self_update
# description: Обновляет Extella из GitHub одной кнопкой: качает свежий toolbar.js в папку Electron + прогоняет install.py пака (эксперты+каталоги) под токеном аккаунта. Возвращает {status, toolbar_updated, seeded, message}. После — перезапустить Extella (Cmd+Q).
def wz_self_update(what="all"):
    import os, sys, json, ssl, tarfile, tempfile, subprocess, urllib.request
    RAW = "https://raw.githubusercontent.com/AnvarBakiyev/extella-marketplace-pack/main/toolbar/toolbar.js"
    TARBALL = "https://github.com/AnvarBakiyev/extella-marketplace-pack/archive/refs/heads/main.tar.gz"
    res = {"status": "success", "toolbar_updated": False, "seeded": False, "message": ""}
    import shutil
    ctx = ssl.create_default_context()
    try:
        import certifi; ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception: pass

    # Загрузка в файл: СНАЧАЛА curl (системные сертификаты — как у пользователя вручную, надёжно),
    # фолбэк — python urllib. Возвращает (ok, err).
    def _dl_to(url, dest, timeout=180):
        curl = shutil.which("curl")
        if curl:
            try:
                r = subprocess.run([curl, "-fsSL", url, "-o", dest], capture_output=True, text=True, timeout=timeout)
                if r.returncode == 0 and os.path.exists(dest) and os.path.getsize(dest) > 0:
                    return True, ""
                cerr = (r.stderr or "").strip()[-80:]
            except Exception as e:
                cerr = str(e)[:80]
        else:
            cerr = "нет curl"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "extella-updater"})
            data = urllib.request.urlopen(req, timeout=timeout, context=ctx).read()
            open(dest, "wb").write(data)
            return (os.path.getsize(dest) > 0), ""
        except Exception as e:
            return False, "curl:%s / py:%s" % (cerr, str(e)[:60])

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
            tmpf = target + ".new"
            ok, err = _dl_to(RAW, tmpf)
            if ok:
                try:
                    data = open(tmpf, "rb").read()
                    if b"Extella Plugins" in data or b"renderApps" in data:   # sanity: это наш toolbar
                        if os.path.exists(target):
                            try: shutil.copy(target, target + ".bak")
                            except Exception: pass
                        os.replace(tmpf, target)
                        res["toolbar_updated"] = True
                    else:
                        res["message"] += "toolbar.js не прошёл проверку; "
                        try: os.remove(tmpf)
                        except Exception: pass
                except Exception as e:
                    res["message"] += "toolbar-запись: " + str(e)[:60] + "; "
            else:
                res["message"] += "toolbar-загрузка: " + err + "; "
        else:
            res["message"] += "папка Extella не найдена; "

    # 2. эксперты + каталоги: скачать пак-тарбол → install.py (использует config.json аккаунта)
    if what in ("all", "server"):
        try:
            tmp = tempfile.mkdtemp(prefix="extella_upd_")
            tgz = os.path.join(tmp, "pack.tgz")
            ok, err = _dl_to(TARBALL, tgz, timeout=180)
            if not ok:
                res["message"] += "пак-загрузка: " + err + "; "
                raise RuntimeError("tarball")
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
