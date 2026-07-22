# expert: app_install
# description: Ставит стороннее приложение по рецепту Pinokio через единый runtime Extella, изолированный каталог и проверяемый реестр. Результат стороннего рецепта не считается гарантированной возможностью Extella.
def app_install(repo="", app_id="", branch="main"):
    import os, json, subprocess, shutil, re, shlex, urllib.parse
    def err(m): return json.dumps({"status":"error","message":m,"app_id":app_id}, ensure_ascii=False)
    repo=(repo or "").strip()
    if not app_id:
        app_id = re.sub(r"[^a-z0-9]+","_", (repo.rstrip("/").split("/")[-1] or "app").lower())
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,119}", str(app_id)) or ".." in str(app_id).split("/"):
        return err("Некорректный app_id")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,119}", str(branch)) or ".." in str(branch).split("/"):
        return err("Некорректная Git-ветка")
    try:
        from extella_expert_bridge import locations, path_or_error, resolve_pinokio_recipe
        native = locations()
    except Exception:
        return err("Системный runtime Extella не установлен. Запустите Repair Extella Client.")
    root = os.path.join(native["apps_root"], app_id)
    node, node_state = path_or_error("node", repair=True)
    if not node: return err(node_state.get("message") or "Node.js недоступен")
    git, git_state = path_or_error("git", repair=True)
    if not git: return err(git_state.get("message") or "Git недоступен")
    # 1. клон / локальная папка
    if repo.startswith("https://"):
        parsed = urllib.parse.urlsplit(repo)
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            return err("HTTPS Git URL содержит запрещённые учётные данные или параметры")
        if os.path.isdir(os.path.join(root,".git")):
            updated=subprocess.run([git,"-C",root,"pull","--ff-only","--depth","1"],capture_output=True,text=True,timeout=180)
            if updated.returncode != 0: return err("Не удалось безопасно обновить сторонний источник")
        else:
            os.makedirs(os.path.dirname(root),exist_ok=True); shutil.rmtree(root,ignore_errors=True)
            r=subprocess.run([git,"clone","--depth","1","-b",branch,repo,root],capture_output=True,text=True,timeout=300)
            if r.returncode!=0:
                r=subprocess.run([git,"clone","--depth","1",repo,root],capture_output=True,text=True,timeout=300)
                if r.returncode!=0: return err("Клонирование стороннего источника завершилось ошибкой")
    else:
        return err("Поддерживаются только HTTPS Git-источники; локальные и SSH-пути не являются воспроизводимой поставкой")
    if not (os.path.exists(os.path.join(root,"install.js")) or os.path.exists(os.path.join(root,"pinokio.js"))):
        return err("в репо нет install.js/pinokio.js — не Pinokio-рецепт")
    # 2. общий ограниченный резолвер → плоские шаги
    entry="install.js" if os.path.exists(os.path.join(root,"install.js")) else "pinokio.js"
    resolved=resolve_pinokio_recipe(root, entry)
    if resolved.get("status") == "error":
        return err(resolved.get("message") or "рецепт не прошёл безопасный резолвер")
    steps=resolved.get("steps",[])
    if not steps:
        _why="; ".join((resolved.get("errors") or [])+(resolved.get("whenErrors") or []))[:200]
        return err("Рецепт приложения не дал ни одного шага для этой платформы"+(" ("+_why+")" if _why else "")+
                   ". Это ошибка на нашей стороне, не ваша — напишите нам, приложив это сообщение.")
    # 2.5 РАНТАЙМ-БУТСТРАП: доставить пакет-менеджеры, которые нужны рецепту (как встроенные у Pinokio)
    def _ensure_runtime(steps):
        allmsg = " ".join(m for st in steps if st.get("method")=="shell.run" for m in (st.get("params",{}).get("message") or []))
        got, extra_path, resolved = [], [os.path.dirname(git), os.path.dirname(node)], {}
        probes = {
            "python": ("python ", "python3 "),
            "uv": ("uv ",), "conda": ("conda ", "conda activate"),
            "npm": ("npm ",), "npx": ("npx ",), "pnpm": ("pnpm ",), "yarn": ("yarn ",),
        }
        for tool, markers in probes.items():
            if not any(marker in allmsg for marker in markers):
                continue
            path, state = path_or_error(tool, repair=True)
            if not path:
                return None, [p for p in extra_path if p], got, state.get("message") or (tool + " недоступен"), resolved
            resolved[tool] = path
            extra_path.append(os.path.dirname(path))
            if state.get("changed"): got.append(tool)
        return True, list(dict.fromkeys(p for p in extra_path if p)), got, "", resolved

    ok_rt, RT_PATH, rt_got, rt_err, resolved_tools = _ensure_runtime(steps)
    if ok_rt is None:
        return err(rt_err)

    # 3. исполнить shell-шаги в venv
    def _best_py():
        checked_python, _state = path_or_error("python", repair=False)
        return checked_python
    def venv_py(vp):
        vabs=os.path.normpath(os.path.join(root,vp))
        py=os.path.join(vabs,"Scripts","python.exe") if os.name == "nt" else os.path.join(vabs,"bin","python")
        if not os.path.exists(py):
            bootstrap_python = _best_py()
            if not bootstrap_python: return None
            subprocess.run([bootstrap_python,"-m","venv",vabs],capture_output=True,text=True,timeout=120)
        return py
    done=0
    for st in steps:
        meth=st.get("method")
        if meth=="fs.rm":
            # рецепты чистят битые остатки прошлых попыток (searxng: rm app, если
            # в нём нет requirements.txt) — без этого клон пропускался «app уже есть»
            _tgt=os.path.normpath(os.path.join(root,(st.get("params",{}) or {}).get("path","") or ""))
            if _tgt.startswith(os.path.normpath(root)+os.sep):  # только внутри папки приложения
                shutil.rmtree(_tgt, ignore_errors=True)
            continue
        if meth!="shell.run": continue
        p=st.get("params",{}); cwd=os.path.normpath(os.path.join(root,p.get("path","") or ""))
        os.makedirs(cwd,exist_ok=True)
        env=dict(os.environ)
        if RT_PATH: env["PATH"]=os.pathsep.join(RT_PATH)+os.pathsep+env.get("PATH","")
        if p.get("venv"):
            vpy=venv_py(p["venv"])
            if not vpy or not os.path.isfile(vpy): return err("Не удалось создать изолированное Python-окружение")
            env["VIRTUAL_ENV"]=os.path.dirname(os.path.dirname(vpy))
            venv_bin = os.path.join(env["VIRTUAL_ENV"], "Scripts" if os.name == "nt" else "bin")
            env["PATH"]=venv_bin+os.pathsep+env.get("PATH","")
            env.setdefault("UV_SYSTEM_PYTHON","0")
        for m in (p.get("message") or []):
            m2=m.replace("uv pip","pip") if "uv" not in resolved_tools else m
            if re.search(r"(?:token|secret|password|passwd|api[-_]?key)", m2, re.I):
                return err("Секреты запрещено передавать в аргументах установочного процесса")
            if re.search(r"[;&|><`]", m2):
                return err("Сложные shell-цепочки стороннего рецепта не поддерживаются безопасным установщиком")
            try:
                argv = shlex.split(m2, posix=(os.name != "nt"))
            except ValueError:
                return err("Команда стороннего рецепта не прошла безопасный разбор")
            if not argv:
                continue
            local = os.path.join(env.get("VIRTUAL_ENV", ""), "Scripts" if os.name == "nt" else "bin", argv[0]) if env.get("VIRTUAL_ENV") else ""
            if os.name == "nt" and local and not os.path.splitext(local)[1]: local += ".exe"
            aliases = {"python3":"python", "python.exe":"python", "node.exe":"node",
                       "npm.cmd":"npm", "npx.cmd":"npx", "conda.exe":"conda"}
            if os.path.isabs(argv[0]) and os.path.isfile(argv[0]):
                executable = argv[0]
            elif local and os.path.isfile(local):
                executable = local
            elif argv[0] == "git":
                executable = git
            elif argv[0] in resolved_tools:
                executable = resolved_tools[argv[0]]
            else:
                executable, state = path_or_error(aliases.get(argv[0].lower(), argv[0]), repair=True)
                if not executable:
                    return err(state.get("message") or (argv[0] + " недоступен"))
            argv[0] = executable
            # идемпотентность: git clone во внутр. папку падает на повторе → пропускаем, если папка уже склонирована
            if os.path.basename(executable).lower().startswith("git") and len(argv) > 2 and argv[1] == "clone":
                tgt=os.path.join(cwd, argv[-1])
                if os.path.isdir(os.path.join(tgt,".git")):
                    continue
                shutil.rmtree(tgt, ignore_errors=True)  # чистим частичный клон
            r=subprocess.run(argv,shell=False,cwd=cwd,env=env,capture_output=True,text=True,timeout=900)
            if r.returncode!=0:
                return err("Установка остановилась на шаге рецепта: «"+m2[:80]+"». Причина: "+
                           "команда вернула ненулевой код "+str(r.returncode)+
                           ". Что делать: нажмите «Установить» ещё раз — шаги продолжатся с места остановки; если повторится, пришлите нам это сообщение целиком.")
        done+=1
    # 4. реестр (старт делаем отдельно через app_start)
    registry_root = native["plugin_registry"]
    def _reg_path(aid):
        # Имя файла реестра — ПЛОСКОЕ, зеркало тулбарного _safeIdOf (посимвольно,
        # без схлопывания): id со слэшем (cocktailpeanut/searxng.pinokio) писал
        # манифест во вложенную папку, где тулбар его не ищет.
        return os.path.join(registry_root, re.sub(r"[^a-zA-Z0-9]", "_", aid) + ".json")
    reg=_reg_path(app_id)
    os.makedirs(os.path.dirname(reg),exist_ok=True)
    # миграция: убрать легаси-запись по дословному app_id (вложенную при слэше)
    _legacy=os.path.join(registry_root, app_id + ".json")
    if _legacy!=reg and os.path.isfile(_legacy):
        try:
            os.remove(_legacy)
            _ld=os.path.dirname(_legacy)
            if _ld.startswith(registry_root + os.sep) and not os.listdir(_ld): os.rmdir(_ld)
        except Exception: pass
    man={"id":app_id,"name":app_id,"type":"recipe","mode":"app",
         "classification":"third_party_unverified",
         "app":{"root":root,"repo":repo},"experts":[],"installed":True,
         "ui":{"type":"local_server","rootPath":root,"mainFile":"index.html","openInBrowser":False}}
    open(reg,"w",encoding="utf-8").write(json.dumps(man,ensure_ascii=False,indent=2))
    return json.dumps({"status":"success","app_id":app_id,"install_steps":done,
                       "gpu":resolved.get("gpu"),"platform":resolved.get("platform"),
                       "runtimes":rt_got,"message":"установлено по рецепту"}, ensure_ascii=False)
