# expert: kp_resolver
# description: База знаний: ставит движок (Ollama + модель эмбеддингов nomic-embed-text) на устройство. Зови ПЕРЕД первой сборкой базы у нового пользователя.

def kp_resolver() -> str:
    import json, subprocess, time, urllib.request
    try:
        from extella_expert_bridge import path_or_error
        b, runtime = path_or_error("ollama", repair=True)
    except Exception:
        b, runtime = None, {"message":"Системный runtime Extella не установлен. Запустите Repair Extella Client."}
    if not b:
        return json.dumps({"status":"error","message":runtime.get("message") or "Для баз знаний нужен Ollama"}, ensure_ascii=False)
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
