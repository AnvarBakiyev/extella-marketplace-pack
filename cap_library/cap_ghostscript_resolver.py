def cap_ghostscript_resolver(confirm_install="no") -> str:
    import os, subprocess, json
    CANDS = ["/opt/homebrew/bin/gs", "/usr/local/bin/gs", "/opt/local/bin/gs", "/usr/bin/gs"]
    def rec(p):
        d = os.path.expanduser("~/.extella_cli"); os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "ghostscript"), "w").write(p)
    def verify(p):
        try:
            r = subprocess.run([p] + ["--version"], capture_output=True, text=True, timeout=20)
            if r.returncode == 0:
                return (r.stdout or r.stderr).strip().split("\n")[0][:24]
        except Exception: pass
        return None
    for p in CANDS:
        if os.path.exists(p):
            v = verify(p)
            if v: rec(p); return json.dumps({"status":"already","bin_path":p,"version":v,"source":"detected"}, ensure_ascii=False)
    if not confirm_install or confirm_install.startswith("{{") or confirm_install.lower() != "yes":
        return json.dumps({"status":"missing","message":"Ghostscript (сжатие PDF) не установлен. confirm_install='yes' поставит через brew."}, ensure_ascii=False)
    brew = next((b for b in ["/opt/homebrew/bin/brew","/usr/local/bin/brew"] if os.path.exists(b)), None)
    if not brew:
        return json.dumps({"status":"failed","message":"Homebrew не найден — нужен brew или ручная установка."}, ensure_ascii=False)
    env = dict(os.environ); env["NONINTERACTIVE"] = "1"
    try:
        r = subprocess.run([brew] + ["install", "ghostscript"], capture_output=True, text=True, timeout=280, env=env)
    except subprocess.TimeoutExpired:
        # ghostscript тянет зависимости — за 280с мог не успеть. Не врём «не нашли»:
        # проверим, не появился ли бинарь; если нет — честно про «ещё ставится».
        for p in CANDS:
            if os.path.exists(p) and verify(p): rec(p); return json.dumps({"status":"installed","bin_path":p,"version":verify(p),"source":"brew"}, ensure_ascii=False)
        return json.dumps({"status":"installing","message":"Ghostscript ещё ставится (большой пакет). Загляните через минуту и нажмите ещё раз."}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status":"failed","message":"brew упал: " + str(e)[:100]}, ensure_ascii=False)
    # РАНЬШЕ returncode brew не проверялся — упавший install молча шёл к «не нашли»
    # (враньё «поставили»). Теперь: успех — ищем бинарь; провал — отдаём причину brew.
    # + расширенный поиск через `brew --prefix ghostscript` (бинарь бывает вне CANDS).
    extra = []
    try:
        pr = subprocess.run([brew, "--prefix", "ghostscript"], capture_output=True, text=True, timeout=20, env=env)
        if pr.returncode == 0 and pr.stdout.strip():
            extra.append(os.path.join(pr.stdout.strip(), "bin", "gs"))
    except Exception: pass
    for p in CANDS + extra:
        if os.path.exists(p):
            v = verify(p)
            if v: rec(p); return json.dumps({"status":"installed","bin_path":p,"version":v,"source":"brew"}, ensure_ascii=False)
    if r.returncode != 0:
        why = (r.stderr or r.stdout or "").strip().splitlines()
        why = why[-1][:140] if why else ("brew вернул код " + str(r.returncode))
        return json.dumps({"status":"failed","message":"Не удалось установить Ghostscript: " + why + ". Попробуйте ещё раз или установите вручную: brew install ghostscript."}, ensure_ascii=False)
    return json.dumps({"status":"failed","message":"Ghostscript установился, но исполняемый файл не найден в ожидаемых путях. Напишите нам это сообщение."}, ensure_ascii=False)
