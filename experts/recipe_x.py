# expert: recipe_x
# description: Раннер стороннего формата .extella.json: платформенные пути, единый ensure_tool, команды без shell-цепочек и локальный сервис с подтверждённым PID/портом/health-check.

def recipe_x(action="install", recipe=None, app_id=None, root=None):
    import json, os, re, shlex, socket, subprocess, urllib.parse
    from pathlib import Path

    def result(status, message, **values):
        values.update({"status":status, "message":message})
        if app_id: values.setdefault("app_id", app_id)
        return json.dumps(values, ensure_ascii=False)

    if isinstance(recipe, str) and recipe.strip():
        try:
            recipe = json.loads(recipe)
        except Exception:
            return result("error", "recipe содержит некорректный JSON", error_class="invalid_recipe")
    if recipe is not None and not isinstance(recipe, dict):
        return result("error", "recipe должен быть JSON-объектом", error_class="invalid_recipe")
    try:
        from extella_expert_bridge import locations, path_or_error, service_control
        native = locations()
    except Exception:
        return result("error", "Системный runtime Extella не установлен. Запустите Repair Extella Client.",
                      error_class="client_runtime_missing")

    apps_root = Path(native["apps_root"]).resolve()
    if recipe and not app_id:
        app_id = str(recipe.get("id") or "app")
    if not app_id:
        return result("error", "не указан app_id", error_class="invalid_app_id")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,119}", str(app_id)) or ".." in Path(str(app_id)).parts:
        return result("error", "некорректный app_id", error_class="invalid_app_id")
    target = Path(root).expanduser().resolve() if root else (apps_root / str(app_id)).resolve()
    try:
        target.relative_to(apps_root)
    except ValueError:
        return result("error", "каталог приложения должен находиться внутри данных Extella",
                      error_class="path_outside_extella")

    recipe_path = target / ".extella.json"
    if recipe is None:
        try:
            recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
        except Exception:
            return result("error", "приложение не установлено этим форматом", error_class="not_installed")

    def substitute(value, context):
        if not isinstance(value, str):
            return value
        return re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda match: str(context.get(match.group(1), "")), value)

    def free_port():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
            handle.bind(("127.0.0.1", 0))
            return int(handle.getsockname()[1])

    def context(port):
        import platform
        return {"port":str(port), "platform":os.name, "arch":platform.machine(), "root":str(target), "gpu":"unknown"}

    def environment(step, context_value):
        env = dict(os.environ)
        venv = str(step.get("venv") or "")
        venv_root = (target / venv).resolve() if venv else None
        venv_bin = None
        if venv_root:
            try:
                venv_root.relative_to(target)
            except ValueError:
                raise ValueError("venv outside application")
            venv_bin = venv_root / ("Scripts" if os.name == "nt" else "bin")
            python_path = venv_bin / ("python.exe" if os.name == "nt" else "python")
            if not python_path.is_file():
                python, state = path_or_error("python", repair=False)
                if not python:
                    raise RuntimeError(state.get("message") or "Python unavailable")
                completed = subprocess.run([python, "-m", "venv", str(venv_root)],
                                           capture_output=True, text=True, timeout=300,
                                           check=False, shell=False)
                if completed.returncode != 0:
                    raise RuntimeError("venv creation failed")
            env["VIRTUAL_ENV"] = str(venv_root)
            env["PATH"] = str(venv_bin) + os.pathsep + env.get("PATH", "")
        for key, value in (step.get("env") or {}).items():
            env[str(key)] = str(substitute(str(value), context_value))
        return env, venv_bin

    def command_argv(command, venv_bin, repair):
        if re.search(r"[;&|><`]", command):
            raise ValueError("shell chains are forbidden")
        argv = shlex.split(command, posix=(os.name != "nt"))
        if not argv:
            raise ValueError("empty command")
        if any(re.search(r"(?:token|secret|password|passwd|api[-_]?key)", item, re.I) for item in argv):
            raise ValueError("secret in process arguments")
        executable = Path(argv[0])
        local = (venv_bin / argv[0]) if venv_bin else None
        if os.name == "nt" and local and not local.suffix:
            for suffix in (".exe", ".cmd", ".bat"):
                if local.with_suffix(suffix).is_file():
                    local = local.with_suffix(suffix)
                    break
        aliases = {"python3":"python", "python.exe":"python", "node.exe":"node",
                   "npm.cmd":"npm", "npx.cmd":"npx", "conda.exe":"conda"}
        if executable.is_absolute() and executable.is_file():
            absolute = str(executable)
        elif local and local.is_file():
            absolute = str(local)
        else:
            absolute, state = path_or_error(aliases.get(argv[0].lower(), argv[0]), repair=repair)
            if not absolute:
                raise RuntimeError(state.get("message") or (argv[0] + " unavailable"))
        argv[0] = absolute
        return argv

    registry = Path(native["plugin_registry"])
    registry_path = registry / (re.sub(r"[^a-zA-Z0-9]", "_", str(app_id)) + ".json")

    if action == "install":
        requirements = recipe.get("requires") or []
        if not isinstance(requirements, list):
            return result("error", "requires должен быть списком", error_class="invalid_recipe")
        dependencies = {}
        for name in requirements:
            path, state = path_or_error(str(name), repair=True)
            dependencies[str(name)] = state
            if not path:
                return result("error", state.get("message") or (str(name) + " недоступен"),
                              error_class="dependency_missing", dependencies=dependencies)
        source = recipe.get("source") or {}
        git_url = str(source.get("git") or "")
        if git_url:
            parsed = urllib.parse.urlsplit(git_url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                return result("error", "source.git должен быть HTTPS URL без учётных данных",
                              error_class="unsupported_source")
            git, state = path_or_error("git", repair=True)
            if not git:
                return result("error", state.get("message") or "Git недоступен", error_class="dependency_missing")
            if not (target / ".git").is_dir():
                target.parent.mkdir(parents=True, exist_ok=True)
                completed = subprocess.run([git, "clone", "--depth", "1", git_url, str(target)],
                                           capture_output=True, text=True, timeout=1800,
                                           check=False, shell=False)
                if completed.returncode != 0:
                    return result("error", "клонирование стороннего источника завершилось ошибкой",
                                  error_class="source_install_failed")
        else:
            target.mkdir(parents=True, exist_ok=True)
        port = free_port()
        ctx = context(port)
        completed_steps = 0
        for step in recipe.get("install") or []:
            if not isinstance(step, dict):
                return result("error", "некорректный шаг установки", error_class="invalid_recipe")
            when = step.get("when") or {}
            if any(str(ctx.get(key, "")) != str(value) for key, value in when.items()):
                continue
            command = str(substitute(step.get("run") or "", ctx)).strip()
            if not command:
                continue
            cwd = (target / str(step.get("cwd") or "")).resolve()
            try:
                cwd.relative_to(target)
                env, venv_bin = environment(step, ctx)
                argv = command_argv(command, venv_bin, True)
            except (ValueError, RuntimeError):
                return result("error", "шаг установки не прошёл проверку пути, зависимости или аргументов",
                              error_class="unsafe_recipe")
            cwd.mkdir(parents=True, exist_ok=True)
            completed = subprocess.run(argv, cwd=str(cwd), env=env, capture_output=True, text=True,
                                       timeout=1800, check=False, shell=False)
            if completed.returncode != 0:
                return result("error", "команда установки вернула ненулевой код " + str(completed.returncode),
                              error_class="recipe_step_failed")
            completed_steps += 1
        recipe_path.write_text(json.dumps(recipe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        registry.mkdir(parents=True, exist_ok=True)
        manifest = {"id":str(app_id), "name":str(recipe.get("name") or app_id), "type":"recipe",
                    "classification":"third_party_unverified", "installed":True,
                    "app":{"root":str(target)}, "experts":[]}
        registry_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result("success", "сторонний рецепт установлен", install_steps=completed_steps,
                      dependencies=dependencies)

    if action not in {"start", "restart", "status", "stop"}:
        return result("error", "неподдерживаемое действие", error_class="invalid_action")
    start = recipe.get("start")
    if not isinstance(start, dict):
        return result("error", "у рецепта нет секции start", error_class="invalid_recipe")
    ready = start.get("ready") or {}
    port = int(ready.get("port") or free_port())
    ctx = context(port)
    command = str(substitute(start.get("run") or "", ctx)).strip()
    cwd = (target / str(start.get("cwd") or "")).resolve()
    try:
        cwd.relative_to(target)
        env, venv_bin = environment(start, ctx)
        argv = command_argv(command, venv_bin, False)
    except (ValueError, RuntimeError):
        return result("error", "команда сервиса не прошла проверку пути, зависимости или аргументов",
                      error_class="unsafe_recipe")
    runtime_id = "third-party." + re.sub(r"[^a-z0-9._-]+", "_", str(app_id).lower()).strip("_")[:60]
    health_url = "http://127.0.0.1:%d/" % port
    try:
        state = service_control(action, runtime_id=runtime_id, name=str(app_id), argv=argv,
                                cwd=str(cwd), port=port, health_url=health_url,
                                owner="extella_third_party_app", autostart="disabled",
                                timeout=180, environment=env)
    except Exception:
        return result("error", "операция отклонена диспетчером владельца процесса",
                      error_class="service_control_failed")
    if action in {"start", "restart"} and state.get("status") == "running":
        try:
            manifest = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.is_file() else {}
        except Exception:
            manifest = {}
        manifest["runtime"] = {"id":runtime_id, "argv":argv, "cwd":str(cwd), "port":port,
                               "healthUrl":health_url, "owner":"extella_third_party_app",
                               "autostart":"disabled"}
        manifest["ui"] = {"type":"local_server", "port":port, "url":health_url,
                          "expectsHealth":True, "openInBrowser":False}
        registry.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result("success", "операция выполнена диспетчером Extella",
                  ready=bool(state.get("healthy")), pid=state.get("pid"), port=port,
                  runtime_status=state.get("status"))
