# expert: _etb_srv_extella_travel_agency
# description: Start expert for Travel Agency onboarding bridge: launches local server.py on 127.0.0.1:8766 if not already running (toolbar plugin convention _etb_srv_*).
import json, os, subprocess, socket

def _alive():
    # «Сервер поднялся» = порт слушается. Раньше health бил в /x/status, а тот
    # делает ЖИВЫЕ вызовы к Tourvisor/WhatsApp (до 60с) — при протухшем JWT висит,
    # 3-сек таймаут срабатывал на ЖИВОМ сервере, эксперт решал «не поднялся» и
    # плодил второй процесс на 8766. TCP-connect не зависит от JWT/внешних вызовов.
    try:
        with socket.create_connection(("127.0.0.1", 8766), timeout=1.5):
            return True
    except Exception:
        return False

if _alive():
    result = json.dumps({"status": "success", "note": "already running", "url": "http://127.0.0.1:8766/"})
else:
    plugin_root = os.environ.get("EXTELLA_PLUGIN_ROOT") or os.path.expanduser("~/extella-plugins")
    path = os.path.join(plugin_root, "extella_travel_agency", "server.py")
    if not os.path.exists(path):
        result = json.dumps({"status": "error", "error": "server.py not found: " + path})
    else:
        subprocess.Popen(["nohup", "python3", path], stdout=open("/tmp/ta_onboarding.log", "a"),
                         stderr=subprocess.STDOUT, start_new_session=True)
        import time
        ok = False
        for _ in range(10):
            time.sleep(1)
            if _alive():
                ok = True
                break
        result = json.dumps({"status": "success" if ok else "error",
                             "note": "started" if ok else "did not come up, see /tmp/ta_onboarding.log",
                             "url": "http://127.0.0.1:8766/"})
result
