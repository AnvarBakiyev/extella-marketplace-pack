# expert: app_uninstall
# description: Безопасно удаляет стороннее приложение: останавливает только подтверждённый процесс Extella, проверяет освобождение порта, затем удаляет каталог и локальную запись реестра.

def app_uninstall(app_id="", root=""):
    import json, os, re, shutil
    from pathlib import Path

    def out(**values):
        values.setdefault("app_id", app_id)
        return json.dumps(values, ensure_ascii=False)

    try:
        from extella_expert_bridge import locations, path_or_error, service_control
        native = locations()
    except Exception:
        return out(status="error", error_class="client_runtime_missing",
                   message="Системный runtime Extella не установлен. Запустите Repair Extella Client.")

    apps_root = Path(native["apps_root"]).resolve()
    target = Path(root).expanduser().resolve() if root else (apps_root / str(app_id)).resolve()
    try:
        relative = target.relative_to(apps_root)
    except ValueError:
        return out(status="error", error_class="path_outside_extella",
                   message="Удаление разрешено только в каталоге приложений Extella.")
    if not app_id:
        app_id = relative.as_posix()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,119}", str(app_id)) or ".." in Path(str(app_id)).parts:
        return out(status="error", error_class="invalid_app_id", message="Некорректный app_id.")

    registry_root = Path(native["plugin_registry"])
    candidates = {
        registry_root / (str(app_id) + ".json"),
        registry_root / (str(app_id).replace("/", "_") + ".json"),
        registry_root / (re.sub(r"[^a-zA-Z0-9]", "_", str(app_id)) + ".json"),
        registry_root / (str(app_id).split("/")[-1] + ".json"),
    }
    record = {}
    for candidate in candidates:
        try:
            if candidate.is_file():
                record = json.loads(candidate.read_text(encoding="utf-8"))
                break
        except Exception:
            continue

    runtime = record.get("runtime") if isinstance(record, dict) else None
    if not isinstance(runtime, dict):
        port = (record.get("ui") or {}).get("port") if isinstance(record, dict) else None
        if port:
            python, state = path_or_error("python", repair=False)
            if not python:
                return out(status="error", error_class="dependency_missing",
                           message=state.get("message") or "Python недоступен для проверки процесса.")
            runtime = {
                "id": "third-party." + re.sub(r"[^a-z0-9._-]+", "_", str(app_id).lower()).strip("_")[:60],
                "argv": [python], "cwd": str(target), "port": int(port),
                "healthUrl": "http://127.0.0.1:%d/" % int(port),
                "owner": "extella_third_party_app", "autostart": "disabled",
            }

    if isinstance(runtime, dict):
        try:
            kwargs = {
                "runtime_id": runtime["id"], "name": str(app_id), "argv": list(runtime["argv"]),
                "cwd": runtime["cwd"], "port": int(runtime["port"]),
                "health_url": runtime["healthUrl"], "owner": runtime.get("owner") or "extella_third_party_app",
                "autostart": runtime.get("autostart") or "disabled",
            }
            before = service_control("status", **kwargs)
            if before.get("errorClass") == "port_occupied_by_unowned_process":
                return out(status="error", error_class="unowned_process",
                           message="Порт занят процессом, которым Extella не владеет; удаление остановлено.")
            after = service_control("stop", **kwargs)
            if after.get("status") != "stopped":
                return out(status="error", error_class="service_stop_failed",
                           message="Подтверждённый процесс не остановился; файлы сохранены.")
        except Exception:
            return out(status="error", error_class="service_stop_failed",
                       message="Не удалось безопасно подтвердить остановку процесса; файлы сохранены.")

    if not target.exists():
        for candidate in candidates:
            try:
                candidate.unlink(missing_ok=True)
            except OSError:
                pass
        return out(status="success", removed=False, message="уже удалено")

    total = 0
    for directory, _, files in os.walk(target):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(directory, name))
            except OSError:
                pass
    try:
        shutil.rmtree(target)
    except OSError:
        return out(status="error", error_class="file_remove_failed",
                   message="Не удалось полностью удалить файлы приложения.")
    for candidate in candidates:
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            pass
    return out(status="success", removed=True, freed_mb=round(total / 1048576),
               message="приложение и подтверждённый runtime удалены")
