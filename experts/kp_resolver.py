# expert: kp_resolver
# description: База знаний: ставит движок (Ollama + модель эмбеддингов nomic-embed-text) на устройство. Зови ПЕРЕД первой сборкой базы у нового пользователя.

def kp_resolver() -> str:
    import os, json, subprocess, time, urllib.request
    def ob():
        import shutil
        cands = ["/usr/local/bin/ollama","/opt/homebrew/bin/ollama",
                 "/Applications/Ollama.app/Contents/Resources/ollama",
                 os.path.expanduser("~/Applications/Ollama.app/Contents/Resources/ollama")]
        for p in cands:
            if os.path.exists(p): return p
        w = shutil.which("ollama")
        return w or ""
    b = ob()
    if not b:
        brew = "/opt/homebrew/bin/brew" if os.path.exists("/opt/homebrew/bin/brew") else ("/usr/local/bin/brew" if os.path.exists("/usr/local/bin/brew") else "")
        if not brew:
            return json.dumps({"status":"error","message":"Для баз знаний нужен бесплатный движок Ollama. Установи его: https://ollama.com/download — открой приложение, затем нажми «Установить базу» снова."}, ensure_ascii=False)
        try: subprocess.run([brew,"install","ollama"], capture_output=True, text=True, timeout=600)
        except Exception as e: return json.dumps({"status":"error","message":"Не удалось поставить Ollama: "+str(e)[:90]}, ensure_ascii=False)
        b = ob()
        if not b: return json.dumps({"status":"error","message":"Ollama поставлен, но бинарь не найден."}, ensure_ascii=False)
    def serving():
        try: urllib.request.urlopen("http://localhost:11434/api/version", timeout=3); return True
        except Exception: return False
    if not serving():
        subprocess.Popen([b,"serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(12):
            time.sleep(2)
            if serving(): break
    if not serving(): return json.dumps({"status":"error","message":"Ollama не запускается."}, ensure_ascii=False)
    have = False
    try:
        r = subprocess.run([b,"list"], capture_output=True, text=True, timeout=30)
        have = "nomic-embed-text" in (r.stdout or "")
    except Exception: pass
    if not have:
        try: subprocess.run([b,"pull","nomic-embed-text"], capture_output=True, text=True, timeout=900)
        except Exception as e: return json.dumps({"status":"error","message":"Не удалось скачать модель эмбеддингов: "+str(e)[:90]}, ensure_ascii=False)
    return json.dumps({"status":"ok","message":"Движок знаний готов (Ollama + nomic-embed-text)."}, ensure_ascii=False)