# expert: _etb_srv_extella_contracts
# description: Start expert for Extella Contract Agent onboarding bridge: launches local server.py on 127.0.0.1:8767 if not already running (toolbar plugin convention _etb_srv_*).
import json, os, subprocess, urllib.request

def _alive():
    try:
        urllib.request.urlopen("http://127.0.0.1:8767/x/status", timeout=3)
        return True
    except Exception:
        return False

if _alive():
    result = json.dumps({"status": "success", "note": "already running", "url": "http://127.0.0.1:8767/"})
else:
    plugin_root = os.environ.get("EXTELLA_PLUGIN_ROOT") or os.path.expanduser("~/extella-plugins")
    path = os.path.join(plugin_root, "extella_contract_agent", "server.py")
    if not os.path.exists(path):
        result = json.dumps({"status": "error", "error": "server.py not found: " + path})
    else:
        subprocess.Popen(["nohup", "python3", path], stdout=open("/tmp/extella_contracts.log", "a"),
                         stderr=subprocess.STDOUT, start_new_session=True)
        import time
        ok = False
        for _ in range(10):
            time.sleep(1)
            if _alive():
                ok = True
                break
        result = json.dumps({"status": "success" if ok else "error",
                             "note": "started" if ok else "did not come up, see /tmp/extella_contracts.log",
                             "url": "http://127.0.0.1:8767/"})
result
