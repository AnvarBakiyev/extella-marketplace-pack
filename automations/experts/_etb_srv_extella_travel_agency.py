# expert: _etb_srv_extella_travel_agency
# description: Запускает сторонний Travel Agency bridge через общий диспетчер Extella с подтверждённым PID, портом и HTTP health-check.
import json, os

try:
    from extella_expert_bridge import locations, path_or_error, service_control
    native = locations()
    python, state = path_or_error("python", repair=False)
    path = os.path.join(native["plugins_root"], "extella_travel_agency", "server.py")
    if not python:
        result = json.dumps({"status":"error", "error_class":"dependency_missing",
                             "message":state.get("message") or "Python недоступен"}, ensure_ascii=False)
    elif not os.path.isfile(path):
        result = json.dumps({"status":"error", "error_class":"plugin_incomplete",
                             "message":"Travel Agency server.py не установлен"}, ensure_ascii=False)
    else:
        running = service_control(
            "start", runtime_id="extella_travel_agency", name="Travel Agency",
            argv=[python, path], cwd=os.path.dirname(path), port=8766,
            health_url="http://127.0.0.1:8766/", owner="extella_travel_agency",
            autostart="disabled", timeout=30,
        )
        result = json.dumps({"status":"success" if running.get("status") == "running" else "error",
                             "pid":running.get("pid"), "port":8766,
                             "ready":bool(running.get("healthy")),
                             "url":"http://127.0.0.1:8766/"}, ensure_ascii=False)
except Exception:
    result = json.dumps({"status":"error", "error_class":"service_control_failed",
                         "message":"Travel Agency runtime не прошёл проверку владельца и health-check"},
                        ensure_ascii=False)
result
