# expert: cap_img2pdf_resolver
# description: Установка и проверка инструмента «img2pdf (картинки → PDF)» (brew). Зови ПЕРЕД первым использованием этой способности.

def cap_img2pdf_resolver(confirm_install="no") -> str:
    # Составная установка: несколько частей (brew + pip) + языковые данные + правильный PATH.
    import os, subprocess, sys, json, shutil, urllib.request
    BREW = []
    PIP = ["img2pdf"]
    DRIVER = "img2pdf"
    PATH_ADD = []
    TESS = None
    def rec(p):
        d = os.path.expanduser("~/.extella_cli"); os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "img2pdf"), "w").write(p)
    def aug():
        return os.pathsep.join(PATH_ADD + [os.environ.get("PATH", "")])
    def driver_ok():
        p = shutil.which(DRIVER, path=aug())
        if not p: return None
        try:
            e = dict(os.environ); e["PATH"] = aug()
            r = subprocess.run([p, "--version"], capture_output=True, text=True, timeout=40, env=e)
            if r.returncode == 0: return p
        except Exception: pass
        return None
    def ensure_tess():
        if not TESS: return
        dirs = TESS.get("dirs") or [TESS.get("dir", "~/.extella_cli/tessdata")]
        td = None
        for c in dirs:
            c = os.path.expanduser(c)
            if os.path.isdir(c): td = c; break
        if not td:
            td = os.path.expanduser(dirs[0])
            try: os.makedirs(td, exist_ok=True)
            except Exception: return
        for name, url in TESS["files"].items():
            f = os.path.join(td, name + ".traineddata")
            if not os.path.exists(f) or os.path.getsize(f) < 1000:
                try: urllib.request.urlretrieve(url, f)
                except Exception: pass
    p = driver_ok()
    if p:
        ensure_tess(); rec(p)
        return json.dumps({"status": "already", "bin_path": p, "driver": DRIVER, "source": "detected"}, ensure_ascii=False)
    if not confirm_install or confirm_install.startswith("{{") or confirm_install.lower() != "yes":
        return json.dumps({"status": "missing", "message": "img2pdf (картинки → PDF) не установлен. confirm_install='yes' поставит все части."}, ensure_ascii=False)
    brew = next((b for b in ["/opt/homebrew/bin/brew", "/usr/local/bin/brew"] if os.path.exists(b)), None)
    if BREW and not brew:
        return json.dumps({"status": "failed", "message": "Homebrew не найден для системных частей (" + ", ".join(BREW) + ")."}, ensure_ascii=False)
    log = []
    env = dict(os.environ); env["NONINTERACTIVE"] = "1"
    for f in BREW:
        try: subprocess.run([brew, "install", f], capture_output=True, text=True, timeout=600, env=env)
        except Exception as e: log.append("brew " + f + ": " + str(e)[:60])
    for pk in PIP:
        try: subprocess.run([sys.executable, "-m", "pip", "install", "-q", pk], capture_output=True, text=True, timeout=420)
        except Exception as e: log.append("pip " + pk + ": " + str(e)[:60])
    ensure_tess()
    p = driver_ok()
    if p:
        rec(p)
        return json.dumps({"status": "installed", "bin_path": p, "driver": DRIVER, "parts": BREW + PIP, "source": "composite"}, ensure_ascii=False)
    return json.dumps({"status": "failed", "message": "Поставили части, но " + DRIVER + " не запускается", "log": log[:4]}, ensure_ascii=False)