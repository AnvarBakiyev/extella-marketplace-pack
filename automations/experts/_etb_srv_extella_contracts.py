# expert: _etb_srv_extella_contracts
# description: Запускает сторонний Contract Agent bridge через общий диспетчер Extella с подтверждённым PID, портом и HTTP health-check.
import json, os

try:
    from extella_expert_bridge import locations, path_or_error, service_control
    native = locations()
    python, state = path_or_error("python", repair=False)
    path = os.path.join(native["plugins_root"], "extella_contract_agent", "server.py")
    if not python:
        result = json.dumps({"status":"error", "error_class":"dependency_missing",
                             "message":state.get("message") or "Python недоступен"}, ensure_ascii=False)
    elif not os.path.isfile(path):
        result = json.dumps({"status":"error", "error_class":"plugin_incomplete",
                             "message":"Contract Agent server.py не установлен"}, ensure_ascii=False)
    else:
        running = service_control(
            "start", runtime_id="extella_contract_agent", name="Contract Agent",
            argv=[python, path], cwd=os.path.dirname(path), port=8767,
            health_url="http://127.0.0.1:8767/x/status", owner="extella_contract_agent",
            autostart="disabled", timeout=30,
        )
        result = json.dumps({"status":"success" if running.get("status") == "running" else "error",
                             "pid":running.get("pid"), "port":8767,
                             "ready":bool(running.get("healthy")),
                             "url":"http://127.0.0.1:8767/"}, ensure_ascii=False)
except Exception:
    result = json.dumps({"status":"error", "error_class":"service_control_failed",
                         "message":"Contract Agent runtime не прошёл проверку владельца и health-check"},
                        ensure_ascii=False)
result
