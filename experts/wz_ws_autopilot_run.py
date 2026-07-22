# expert: wz_ws_autopilot_run
# description: Запускает локальный драйвер автопилота воркспейса (copilot/workspace_autopilot.py <ws_id>): он сам делает следующие capability-задачи, пока не упрётся в вопрос/human. Многошагово, без таймаута одного вызова. Возвращает {status, message, ran}.
def wz_ws_autopilot_run(ws_id=""):
    import os, json, subprocess
    if not ws_id or str(ws_id).startswith("{{"):
        return json.dumps({"status": "error", "message": "нужен ws_id"}, ensure_ascii=False)
    try:
        from extella_expert_bridge import locations, path_or_error
        driver = os.path.join(locations()["workspace_root"], "workspace_autopilot.py")
        py, runtime = path_or_error("python", repair=False)
    except Exception:
        driver, py, runtime = None, None, {"message": "Системный runtime Extella не установлен"}
    if not driver:
        return json.dumps({"status": "error",
            "message": "драйвер автопилота не установлен на этом устройстве"}, ensure_ascii=False)
    if not os.path.isfile(driver):
        return json.dumps({"status": "error",
            "message": "пакет Workspace неполный — запустите Repair Extella Client"}, ensure_ascii=False)
    if not py:
        return json.dumps({"status": "error", "message": runtime.get("message") or "Python недоступен"}, ensure_ascii=False)

    logf = os.path.join(os.path.dirname(driver), ".autopilot_%s.log" % str(ws_id)[-8:])
    try:
        with open(logf, "w") as lf:
            p = subprocess.Popen([py, driver, str(ws_id)], cwd=os.path.dirname(driver),
                                 stdout=lf, stderr=subprocess.STDOUT, start_new_session=True)
        # автопилот останавливается на первом вопросе/human — обычно быстро; ждём до ~200с
        try:
            p.wait(timeout=200)
            ran = True
        except subprocess.TimeoutExpired:
            ran = False   # ещё работает — вернём «в фоне»
        tail = ""
        try:
            lines = open(logf, encoding="utf-8", errors="ignore").read().strip().splitlines()
            tail = " · ".join(lines[-3:])[:200]
        except Exception: pass
        msg = ("Автопилот отработал доступные задачи. " + tail) if ran else ("Автопилот идёт в фоне. " + tail)
        return json.dumps({"status": "success", "ran": ran, "driver": "workspace_autopilot", "message": msg}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": "не удалось запустить драйвер: " + str(e)[:100]}, ensure_ascii=False)
