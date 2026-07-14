# name: recipe_x
# description: Раннер формата Extella (.extella.json) — install/start приложения БЕЗ Node и БЕЗ песочницы (рецепт = данные, не код). Подстановки {{port/gpu/platform/arch/root}}, условия when, детект порта из лога (ready.log). Рантайм-бутстрап git/node/python/uv/conda. См. EXTELLA_RECIPE_SPEC.md.
import os, re, sys, json, socket, shutil, subprocess, platform as _pf

# ── окружение ────────────────────────────────────────────────────────────────
def _gpu():
    if sys.platform == "darwin":
        return "apple" if _pf.machine() in ("arm64", "aarch64") else "cpu"
    try:
        subprocess.run(["nvidia-smi"], capture_output=True, timeout=5, check=True); return "nvidia"
    except Exception:
        return "cpu"

def _free_port():
    s = socket.socket(); s.bind(("", 0)); p = s.getsockname()[1]; s.close(); return p

def _ctx(root, port):
    return {"port": str(port), "gpu": _gpu(), "platform": sys.platform,
            "arch": _pf.machine(), "root": root}

def _sub(val, ctx):
    if not isinstance(val, str) or "{{" not in val:
        return val
    return re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda m: str(ctx.get(m.group(1), "")), val)

def _when_ok(when, ctx):
    if not when:
        return True
    return all(str(ctx.get(k, "")) == str(v) for k, v in when.items())

# ── рантайм-бутстрап (то же, что в app_install: без админа где можно) ─────────
def _ensure_runtime(reqs):
    got = {}
    def has(c): return shutil.which(c) is not None
    for r in (reqs or []):
        if r in ("git",) and not has("git"):
            got[r] = "нужен git (xcode-select --install)"
        elif r == "uv" and not has("uv"):
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "uv"], capture_output=True, timeout=300)
            got[r] = "ok" if has("uv") else "fail"
        elif r == "node" and not has("node"):
            if has("brew"):
                subprocess.run(["brew", "install", "node"], capture_output=True, timeout=900)
            got[r] = "ok" if has("node") else "нужен Node (brew install node)"
        elif r == "conda" and not has("conda"):
            got[r] = "conda ставится по требованию рецепта"
        else:
            got[r] = "ok" if has(r) else "present?"
    return got

def _venv_env(root, venv, extra, ctx):
    env = dict(os.environ)
    if venv:
        vpath = os.path.join(root, venv)
        if not os.path.isdir(vpath):
            subprocess.run([sys.executable, "-m", "venv", vpath], capture_output=True, timeout=300)
        env["VIRTUAL_ENV"] = vpath
        env["PATH"] = os.path.join(vpath, "bin") + os.pathsep + env.get("PATH", "")
    for k, v in (extra or {}).items():
        env[str(k)] = _sub(str(v), ctx)
    return env

# ── установка ────────────────────────────────────────────────────────────────
def install(recipe, root=None):
    rid = recipe.get("id", "app")
    root = root or os.path.expanduser("~/extella-apps/" + rid)
    os.makedirs(os.path.dirname(root), exist_ok=True)
    rt = _ensure_runtime(recipe.get("requires"))
    # 1. источник
    src = recipe.get("source") or {}
    if src.get("git") and not os.path.isdir(os.path.join(root, ".git")):
        r = subprocess.run(["git", "clone", "--depth", "1", src["git"], root],
                           capture_output=True, text=True, timeout=1800)
        if r.returncode != 0:
            return {"status": "error", "message": "git clone: " + (r.stderr or "")[-160:], "app_id": rid}
    elif not os.path.isdir(root):
        os.makedirs(root, exist_ok=True)
    # 2. шаги установки
    port = _free_port()
    ctx = _ctx(root, port)
    done = 0
    for step in (recipe.get("install") or []):
        if not _when_ok(step.get("when"), ctx):
            continue
        cmd = _sub(step.get("run", ""), ctx)
        if not cmd.strip():
            continue
        cwd = os.path.join(root, step.get("cwd", "")) if step.get("cwd") else root
        env = _venv_env(root, step.get("venv"), step.get("env"), ctx)
        if not shutil.which("uv"):
            cmd = cmd.replace("uv pip", "pip")
        r = subprocess.run(cmd, shell=True, cwd=cwd, env=env, capture_output=True, text=True, timeout=1800)
        if r.returncode != 0:
            return {"status": "error", "message": "шаг упал: " + cmd[:70] + " | " + (r.stderr or "")[-140:], "app_id": rid}
        done += 1
    # 3. сохранить рецепт рядом (для start)
    json.dump(recipe, open(os.path.join(root, ".extella.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return {"status": "success", "app_id": rid, "root": root, "install_steps": done, "runtimes": rt,
            "gpu": ctx["gpu"], "platform": ctx["platform"]}

# ── запуск ───────────────────────────────────────────────────────────────────
def start(recipe=None, root=None, app_id=None):
    if root is None and app_id:
        root = os.path.expanduser("~/extella-apps/" + app_id)
    if recipe is None:
        rp = os.path.join(root, ".extella.json")
        if not os.path.isfile(rp):
            return {"status": "error", "message": "нет .extella.json — приложение не установлено этим форматом"}
        recipe = json.load(open(rp, encoding="utf-8"))
    st = recipe.get("start")
    if not st:
        return {"status": "error", "message": "у рецепта нет секции start (kind cli?)"}
    port = _free_port()
    ctx = _ctx(root, port)
    cmd = _sub(st.get("run", ""), ctx)
    cwd = os.path.join(root, st.get("cwd", "")) if st.get("cwd") else root
    env = _venv_env(root, st.get("venv"), st.get("env"), ctx)
    logf = os.path.join(root, "server.log")
    lf = open(logf, "w")
    subprocess.Popen(cmd, shell=True, cwd=cwd, env=env, stdout=lf, stderr=subprocess.STDOUT,
                     start_new_session=True)
    # готовность: URL из лога (приём Pinokio on:event) → реальный порт
    ready_log = (st.get("ready") or {}).get("log")
    fixed = (st.get("ready") or {}).get("port")
    import time
    up = False
    for _ in range(25):
        time.sleep(2)
        try:
            txt = open(logf, encoding="utf-8", errors="ignore").read() if os.path.exists(logf) else ""
            if ready_log:
                m = re.search(r"https?://(?:127\.0\.0\.1|localhost|0\.0\.0\.0):(\d{2,5})", txt)
                if m:
                    port = int(m.group(1))
            if fixed:
                port = int(fixed)
        except Exception:
            pass
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.5):
                up = True; break
        except Exception:
            pass
    return {"status": "success" if up else "starting", "app_id": recipe.get("id"), "port": port,
            "url": "http://localhost:%d" % port, "ready": up,
            "message": ("запущено на порту %d" % port) if up else "запускается, порт %d" % port}

# ── точка входа эксперта ─────────────────────────────────────────────────────
def recipe_x(action="install", recipe=None, app_id=None, root=None):
    if isinstance(recipe, str) and recipe.strip():
        try: recipe = json.loads(recipe)
        except Exception: return json.dumps({"status": "error", "message": "recipe: битый JSON"}, ensure_ascii=False)
    if action == "start":
        return json.dumps(start(recipe=recipe, root=root, app_id=app_id), ensure_ascii=False)
    return json.dumps(install(recipe, root=root), ensure_ascii=False)
