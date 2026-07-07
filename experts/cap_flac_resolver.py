# expert: cap_flac_resolver
# description: Установка и проверка инструмента «FLAC (сжать аудио)» (brew). Зови ПЕРЕД первым использованием этой способности.

def cap_flac_resolver(confirm_install="no") -> str:
    import os, subprocess, json
    CANDS = ["/opt/homebrew/bin/flac", "/usr/local/bin/flac"]
    def rec(p):
        d = os.path.expanduser("~/.extella_cli"); os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "flac"), "w").write(p)
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
        return json.dumps({"status":"missing","message":"FLAC (сжать аудио) не установлен. confirm_install='yes' поставит через brew."}, ensure_ascii=False)
    brew = next((b for b in ["/opt/homebrew/bin/brew","/usr/local/bin/brew"] if os.path.exists(b)), None)
    if not brew:
        return json.dumps({"status":"failed","message":"Homebrew не найден — нужен brew или ручная установка."}, ensure_ascii=False)
    env = dict(os.environ); env["NONINTERACTIVE"] = "1"
    try:
        subprocess.run([brew] + ["install", "flac"], capture_output=True, text=True, timeout=280, env=env)
    except Exception as e:
        return json.dumps({"status":"failed","message":"brew упал: " + str(e)[:100]}, ensure_ascii=False)
    for p in CANDS:
        if os.path.exists(p):
            v = verify(p)
            if v: rec(p); return json.dumps({"status":"installed","bin_path":p,"version":v,"source":"brew"}, ensure_ascii=False)
    return json.dumps({"status":"failed","message":"Поставили, но бинарь не находится."}, ensure_ascii=False)