# expert: cap_pandoc_resolver
# description: Установка и проверка инструмента «Pandoc (конвертация документов)» (brew). Зови ПЕРЕД первым использованием этой способности.

def cap_pandoc_resolver(confirm_install="no") -> str:
    import os, subprocess, sys, json, shutil
    def rec(p):
        d = os.path.expanduser("~/.extella_cli"); os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "pandoc"), "w").write(p)
    def verify(p):
        try:
            r = subprocess.run([p] + ["--version"], capture_output=True, text=True, timeout=20)
            if r.returncode == 0:
                return (r.stdout or r.stderr).strip().split("\n")[0][:24]
        except Exception: pass
        return None
    def locate():
        try:
            import importlib; importlib.invalidate_caches()
            import pypandoc as M
            return M.get_pandoc_path()
        except Exception:
            return None
    p = shutil.which("pandoc")
    if p:
        v = verify(p)
        if v: rec(p); return json.dumps({"status":"already","bin_path":p,"version":v,"source":"which"}, ensure_ascii=False)
    p = locate()
    if p and os.path.exists(p):
        v = verify(p)
        if v: rec(p); return json.dumps({"status":"already","bin_path":p,"version":v,"source":"pip"}, ensure_ascii=False)
    if not confirm_install or confirm_install.startswith("{{") or confirm_install.lower() != "yes":
        return json.dumps({"status":"missing","message":"Pandoc (конвертация документов) не установлен. confirm_install='yes' поставит через pip."}, ensure_ascii=False)
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pypandoc_binary"], capture_output=True, text=True, timeout=280)
    except Exception as e:
        return json.dumps({"status":"failed","message":"pip упал: " + str(e)[:100]}, ensure_ascii=False)
    p = locate()
    if p and os.path.exists(p):
        v = verify(p)
        if v: rec(p); return json.dumps({"status":"installed","bin_path":p,"version":v,"source":"pip"}, ensure_ascii=False)
    return json.dumps({"status":"failed","message":"Поставили pip-пакет, но бинарь не найден."}, ensure_ascii=False)