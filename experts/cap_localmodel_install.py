# expert: cap_localmodel_install
# description: Установка локальной модели через Ollama (headless, приватно)

def cap_localmodel_install(model="") -> str:
    # Ставит локальную модель через Ollama. НЕ открывает приложение (служба поднимается headless).
    import os, subprocess, json, re, time, urllib.request
    if not model or model.startswith("{{"): return json.dumps({"status":"error","message":"нужен параметр model"}, ensure_ascii=False)
    try:
        from extella_expert_bridge import path_or_error
        ol, runtime = path_or_error("ollama", repair=True)
    except Exception:
        ol, runtime = None, {"message": "Системный runtime Extella не установлен. Запустите Repair Extella Client."}
    if not ol: return json.dumps({"status":"error","message":runtime.get("message") or "Ollama недоступен"}, ensure_ascii=False)
    def up():
        try: urllib.request.urlopen("http://localhost:11434/api/version", timeout=3); return True
        except Exception: return False
    if not up():
        try: subprocess.Popen([ol,"serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
        except Exception: pass
        time.sleep(2)
    try: lst = subprocess.run([ol,"list"], capture_output=True, text=True, timeout=30).stdout
    except Exception: lst = ""
    if model in lst or model.split(":")[0] in lst:
        return json.dumps({"status":"already","model":model}, ensure_ascii=False)
    d = os.path.expanduser("~/.extella_cli"); os.makedirs(d, exist_ok=True)
    logf = os.path.join(d, "pull_" + re.sub(r'[^A-Za-z0-9]+','_',model)[:40] + ".log")
    try:
        lg = open(logf, "w")
        subprocess.Popen([ol,"pull",model], stdout=lg, stderr=lg, start_new_session=True, close_fds=True)
    except Exception as e:
        return json.dumps({"status":"error","message":"не удалось запустить скачивание: "+str(e)[:100]}, ensure_ascii=False)
    return json.dumps({"status":"pulling","model":model,"message":"Скачивается в фоне (несколько минут). Пользоваться — через ассистента Extella, не через Ollama."}, ensure_ascii=False)