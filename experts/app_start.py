# expert: app_start
# description: Безопасно запускает установленное стороннее приложение через общий диспетчер Extella: один владелец, подтверждённый PID, порт и HTTP health-check.

def app_start(app_id="", root="", entry="start.js"):
    import json, os, re, shlex
    from pathlib import Path

    def err(message, error_class="third_party_recipe"):
        return json.dumps({"status":"error", "error_class":error_class,
                           "message":message, "app_id":app_id}, ensure_ascii=False)

    try:
        from extella_expert_bridge import locations, path_or_error, resolve_pinokio_recipe, service_control
        native = locations()
    except Exception:
        return err("Системный runtime Extella не установлен. Запустите Repair Extella Client.", "client_runtime_missing")

    apps_root = Path(native["apps_root"]).resolve()
    requested = Path(root).expanduser().resolve() if root else (apps_root / str(app_id)).resolve()
    try:
        relative = requested.relative_to(apps_root)
    except ValueError:
        return err("Запуск разрешён только из каталога приложений Extella.", "path_outside_extella")
    if not app_id:
        app_id = relative.as_posix()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,119}", str(app_id)) or ".." in Path(str(app_id)).parts:
        return err("Некорректный app_id.", "invalid_app_id")
    if not requested.is_dir():
        return err("Приложение не установлено.", "not_installed")

    entry = Path(str(entry or "start.js")).name
    for candidate in (entry, "start.js", "run.js", "pinokio.js"):
        if (requested / candidate).is_file():
            entry = candidate
            break
    else:
        return err("В приложении нет поддерживаемого стартового рецепта.")

    resolved = resolve_pinokio_recipe(str(requested), entry)
    if resolved.get("status") == "error":
        return err(resolved.get("message") or "Рецепт запуска не прошёл проверку.")
    shell_steps = [item for item in (resolved.get("steps") or []) if item.get("method") == "shell.run"]
    commands = []
    command_step = None
    for step in shell_steps:
        for message in (step.get("params") or {}).get("message") or []:
            if str(message).strip():
                commands.append(str(message).strip())
                command_step = step
    if len(commands) != 1 or command_step is None:
        return err("Рецепт должен содержать ровно одну команду сервиса; сложные сторонние рецепты не запускаются как гарантированные.")
    command = commands[0]
    if re.search(r"[;&|><`]", command):
        return err("Командные цепочки и перенаправления в сервисном рецепте запрещены.", "unsafe_recipe")
    try:
        argv = shlex.split(command, posix=(os.name != "nt"))
    except ValueError:
        return err("Не удалось разобрать команду запуска.")
    if not argv:
        return err("Команда запуска пуста.")
    if any(re.search(r"(?:token|secret|password|passwd|api[-_]?key)", item, re.I) for item in argv):
        return err("Секреты запрещено передавать в аргументах процесса; используйте переменные окружения.", "secret_in_process_args")

    params = command_step.get("params") or {}
    cwd = (requested / str(params.get("path") or "")).resolve()
    try:
        cwd.relative_to(requested)
    except ValueError:
        return err("Рабочий каталог рецепта выходит за каталог приложения.", "path_outside_app")
    if not cwd.is_dir():
        return err("Рабочий каталог рецепта отсутствует.")

    venv = str(params.get("venv") or "")
    venv_root = (requested / venv).resolve() if venv else None
    venv_bin = None
    if venv_root:
        try:
            venv_root.relative_to(requested)
        except ValueError:
            return err("Каталог окружения выходит за каталог приложения.", "path_outside_app")
        venv_bin = venv_root / ("Scripts" if os.name == "nt" else "bin")

    executable = Path(argv[0])
    if executable.is_absolute() and executable.is_file():
        absolute = str(executable)
    else:
        aliases = {
            "python": "python", "python3": "python", "python.exe": "python",
            "node": "node", "node.exe": "node", "npm": "npm", "npm.cmd": "npm",
            "npx": "npx", "npx.cmd": "npx", "uv": "uv", "uvx": "uvx",
            "conda": "conda", "conda.exe": "conda", "pnpm": "pnpm", "yarn": "yarn",
        }
        local = (venv_bin / argv[0]) if venv_bin else None
        if os.name == "nt" and local and not local.suffix:
            local = local.with_suffix(".exe")
        if local and local.is_file():
            absolute = str(local)
        else:
            tool = aliases.get(argv[0].lower(), argv[0])
            absolute, state = path_or_error(tool, repair=False)
            if not absolute:
                return err(state.get("message") or (argv[0] + " недоступен"), "dependency_missing")
    argv[0] = absolute

    port = resolved.get("port")
    if not port:
        match = re.search(r"(?:--port|--server-port|-p)[= ](\d{2,5})", command)
        port = int(match.group(1)) if match else 7860
    try:
        port = int(port)
    except (TypeError, ValueError):
        return err("Рецепт вернул некорректный порт.")
    if not 1024 <= port <= 65535:
        return err("Порт сервиса вне разрешённого диапазона.")

    environment = dict(os.environ)
    if venv_root and venv_bin:
        environment["VIRTUAL_ENV"] = str(venv_root)
        environment["PATH"] = str(venv_bin) + os.pathsep + environment.get("PATH", "")
    for key, value in (params.get("env") or {}).items():
        environment[str(key)] = str(value)
    runtime_id = "third-party." + re.sub(r"[^a-z0-9._-]+", "_", str(app_id).lower()).strip("_")[:60]
    health_url = "http://127.0.0.1:%d/" % port
    try:
        state = service_control(
            "start", runtime_id=runtime_id, name=str(app_id), argv=argv, cwd=str(cwd),
            port=port, health_url=health_url, owner="extella_third_party_app",
            autostart="disabled", timeout=180, environment=environment,
        )
    except Exception:
        return err("Приложение не прошло проверку PID, владельца порта или HTTP health-check.", "service_health_failed")
    if state.get("status") != "running" or not state.get("healthy") or not state.get("pid"):
        return err("Приложение не подтвердило готовность.", "service_health_failed")

    registry = Path(native["plugin_registry"])
    registry.mkdir(parents=True, exist_ok=True)
    record_path = registry / (re.sub(r"[^a-zA-Z0-9]", "_", str(app_id)) + ".json")
    try:
        record = json.loads(record_path.read_text(encoding="utf-8")) if record_path.is_file() else {}
    except Exception:
        record = {}
    record.update({
        "id": str(app_id), "name": record.get("name") or str(app_id), "type": "recipe",
        "classification": "third_party_unverified", "installed": True,
        "ui": {"type":"local_server", "port":port, "url":health_url,
               "openInBrowser":False, "expectsHealth":True},
        "runtime": {"id":runtime_id, "argv":argv, "cwd":str(cwd), "port":port,
                    "healthUrl":health_url, "owner":"extella_third_party_app",
                    "autostart":"disabled"},
    })
    temporary = record_path.with_suffix(record_path.suffix + ".tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, record_path)
    return json.dumps({"status":"success", "app_id":app_id, "ready":True,
                       "pid":state["pid"], "port":port, "url":health_url,
                       "message":"стороннее приложение запущено и прошло health-check"}, ensure_ascii=False)
