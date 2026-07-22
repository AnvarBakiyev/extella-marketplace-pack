# expert: cap_localmodel_install
# description: Установка локальной модели через Ollama (headless, приватно)

def cap_localmodel_install(model="") -> str:
    # Ставит локальную модель через Ollama. Сервер, который подняла Extella,
    # регистрируется в общем диспетчере — PID/порт и кнопки start/stop видны в
    # Activity Center. Уже запущенный пользователем Ollama не присваиваем себе.
    import json
    import os
    import re
    import subprocess
    import time
    import urllib.request
    from pathlib import Path

    if not model or model.startswith("{{"):
        return json.dumps({"status":"error","message":"нужен параметр model"}, ensure_ascii=False)
    try:
        from extella_expert_bridge import locations, path_or_error, service_control
        ol, runtime = path_or_error("ollama", repair=True)
    except Exception:
        ol, runtime = None, {"message": "Системный runtime Extella не установлен. Запустите Repair Extella Client."}
    if not ol:
        return json.dumps({"status":"error","message":runtime.get("message") or "Ollama недоступен"}, ensure_ascii=False)

    def up():
        try:
            with urllib.request.urlopen("http://127.0.0.1:11434/api/version", timeout=3) as opened:
                return 200 <= int(opened.status) < 400
        except Exception:
            return False

    service = {"owned": False, "pid": None, "port": 11434}
    if not up():
        try:
            state = service_control(
                "start",
                runtime_id="extella.ollama",
                name="Ollama — локальные модели",
                argv=[ol, "serve"],
                cwd=str(Path(ol).resolve().parent),
                port=11434,
                health_url="http://127.0.0.1:11434/api/version",
                owner="extella_catalog_model",
                autostart="disabled",
                timeout=60,
            )
            service = {
                "owned": bool(state.get("canStop")),
                "pid": state.get("pid"),
                "port": state.get("port") or 11434,
            }
        except Exception:
            return json.dumps({
                "status":"error",
                "error_class":"service_health_failed",
                "message":"Ollama не запустился или порт 11434 занят посторонним процессом.",
            }, ensure_ascii=False)
    else:
        try:
            state = service_control(
                "status",
                runtime_id="extella.ollama",
                name="Ollama — локальные модели",
                argv=[ol, "serve"],
                cwd=str(Path(ol).resolve().parent),
                port=11434,
                health_url="http://127.0.0.1:11434/api/version",
                owner="extella_catalog_model",
                autostart="disabled",
            )
            service = {
                "owned": bool(state.get("canStop")),
                "pid": state.get("pid"),
                "port": state.get("port") or 11434,
            }
        except Exception:
            # Живой внешний Ollama допустим: пользуемся им, но не показываем
            # чужой PID как принадлежащий Extella и никогда его не останавливаем.
            service = {"owned": False, "pid": None, "port": 11434}
    try:
        lst = subprocess.run([ol,"list"], capture_output=True, text=True, timeout=30, check=False, shell=False).stdout
    except Exception:
        lst = ""
    if model in lst or model.split(":")[0] in lst:
        return json.dumps({"status":"already","model":model,"runtime":service}, ensure_ascii=False)
    try:
        d = os.path.join(locations()["logs_root"], "model-downloads")
    except Exception:
        return json.dumps({"status":"error","message":"Системный runtime Extella не установлен. Запустите Repair Extella Client."}, ensure_ascii=False)
    os.makedirs(d, exist_ok=True)
    logf = os.path.join(d, "pull_" + re.sub(r'[^A-Za-z0-9]+','_',model)[:40] + ".log")
    try:
        lg = open(logf, "w")
        subprocess.Popen(
            [ol,"pull",model], stdout=lg, stderr=lg,
            start_new_session=True, close_fds=True, shell=False,
        )
        lg.close()
    except Exception as e:
        return json.dumps({"status":"error","message":"не удалось запустить скачивание: "+str(e)[:100]}, ensure_ascii=False)
    return json.dumps({
        "status":"pulling",
        "model":model,
        "runtime":service,
        "message":"Скачивается в фоне (несколько минут). Повторный клик безопасно проверит готовность.",
    }, ensure_ascii=False)
