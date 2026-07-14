# expert: hf_space_install
# description: Детерминированный установщик HF Gradio-Space как плагина (БЕЗ ИИ-агента): читает gradio_api/info, генерит и сохраняет прокси-эксперт <plugin_id>_run, пишет index.html + реестр, поднимает локальный сервер. Прокси-эксперт создаётся ВСЕГДА. Не-gradio спейсы (веб-приложения) честно отклоняет.
def hf_space_install(space="", plugin_id="", display_name="", port="", root_path="", registry_path=""):
    import os, json, re, urllib.request, subprocess, sys, time
    def err(m, code="error"):
        return json.dumps({"status": code, "message": m, "plugin_id": plugin_id}, ensure_ascii=False)
    space = (space or "").strip().strip("/")
    if "/" not in space:
        return err("space должен быть owner/name")
    owner, name = space.split("/", 1)
    plugin_id = plugin_id or ("hf_" + re.sub(r"[^a-z0-9]+", "_", space.lower()))
    display_name = display_name or name
    port = str(port or (8800 + (sum(ord(c) for c in plugin_id) % 300)))
    home = os.path.expanduser("~")
    root_path = os.path.expanduser(root_path or (home + "/extella-plugins/" + plugin_id))
    registry_path = os.path.expanduser(registry_path or (home + "/extella-plugins/_registry/" + plugin_id + ".json"))
    proxy = plugin_id + "_run"
    start_expert = "_etb_srv_" + plugin_id
    host = "https://%s-%s.hf.space" % (owner.lower().replace("_", "-"), name.lower().replace("_", "-").replace(".", "-"))

    # 1) интроспекция gradio API
    try:
        info = json.load(urllib.request.urlopen(host + "/gradio_api/info", timeout=25))
    except Exception:
        try:
            info = json.load(urllib.request.urlopen(host + "/info", timeout=25))
        except Exception as e:
            return err("это не Gradio-Space (нет gradio_api/info) — вероятно веб-приложение; детерминированная установка не подходит: " + str(e)[:80], "not_gradio")
    eps = info.get("named_endpoints") or {}
    if not eps:
        return err("у Space нет именованных эндпоинтов gradio", "not_gradio")
    # выбираем первый эндпоинт с параметрами
    api_name, spec = None, None
    for k, v in eps.items():
        if (v or {}).get("parameters"):
            api_name, spec = k, v; break
    if not api_name:
        api_name, spec = list(eps.items())[0]
    params = (spec or {}).get("parameters", []) or []
    def ptype(p):
        t = (p.get("python_type") or {}).get("type") or p.get("type") or "str"
        return str(t).lower()
    fields = []
    for i, p in enumerate(params):
        lbl = p.get("label") or p.get("parameter_name") or ("arg%d" % i)
        t = ptype(p)
        isfile = ("file" in t) or ("filepath" in t) or ("image" in t) or (p.get("component") in ("Image", "Audio", "File", "Video"))
        default = p.get("parameter_default")
        fields.append({"i": i, "label": lbl, "type": t, "file": bool(isfile), "default": default,
                       "has_default": ("parameter_default" in p)})
    has_file = any(f["file"] for f in fields)

    # 2) прокси-эксперт: обобщённый, по позиционным аргументам (args_json) + опц. file_b64
    proxy_code = (
        "# expert: %s\n" % proxy +
        "# description: Прокси к HF Gradio-Space %s (эндпоинт %s). Вызов из панели плагина. Параметры: args_json (JSON-список позиционных аргументов), file_b64 (опц.).\n" % (space, api_name) +
        "def %s(args_json=\"[]\", file_b64=\"\"):\n" % proxy +
        "    import json, os, base64, tempfile, subprocess, sys\n"
        "    def _ensure():\n"
        "        try:\n"
        "            import gradio_client  # noqa\n"
        "        except Exception:\n"
        "            subprocess.run([sys.executable, \"-m\", \"pip\", \"install\", \"-q\", \"gradio_client\"], timeout=300)\n"
        "    _ensure()\n"
        "    from gradio_client import Client\n"
        "    try:\n"
        "        from gradio_client import handle_file\n"
        "    except Exception:\n"
        "        handle_file = None\n"
        "    # HF-токен (для приватных/лимитированных Space) — best-effort из Extella KV\n"
        "    tok = os.environ.get(\"HF_TOKEN\", \"\")\n"
        "    if not tok:\n"
        "        try:\n"
        "            import urllib.request\n"
        "            atp = os.path.expanduser(\"~/.extella/api_token.txt\")\n"
        "            at = open(atp).read().strip() if os.path.exists(atp) else \"\"\n"
        "            if not at:\n"
        "                cfg = os.path.expanduser(\"~/extella_wizard/app/config.json\")\n"
        "                at = json.load(open(cfg)).get(\"auth_token\", \"\") if os.path.exists(cfg) else \"\"\n"
        "            if at:\n"
        "                rq = urllib.request.Request(\"https://api.extella.ai/api/kv/get\", data=json.dumps({\"key\": \"huggingface_token\"}).encode(), headers={\"X-Auth-Token\": at, \"Content-Type\": \"application/json\"})\n"
        "                v = json.load(urllib.request.urlopen(rq, timeout=20)).get(\"value\")\n"
        "                if v: tok = v\n"
        "        except Exception: pass\n"
        "    if tok: os.environ[\"HF_TOKEN\"] = tok\n"
        "    try:\n"
        "        args = json.loads(args_json) if args_json else []\n"
        "        if not isinstance(args, list): args = [args]\n"
        "    except Exception:\n"
        "        args = [args_json]\n"
        "    if file_b64:\n"
        "        try:\n"
        "            raw = base64.b64decode(file_b64.split(\",\",1)[1] if \",\" in file_b64[:64] else file_b64)\n"
        "            fp = tempfile.mktemp()\n"
        "            open(fp, \"wb\").write(raw)\n"
        "            fa = handle_file(fp) if handle_file else fp\n"
        "            args = [fa] + args\n"
        "        except Exception as e:\n"
        "            return json.dumps({\"status\": \"error\", \"message\": \"file: \" + str(e)[:80]}, ensure_ascii=False)\n"
        "    try:\n"
        "        try: c = Client(%r, hf_token=tok or None)\n" % space +
        "        except TypeError: c = Client(%r)\n" % space +
        "        res = c.predict(*args, api_name=%r)\n" % api_name +
        "        out = res\n"
        "        if isinstance(res, (list, tuple)): out = [str(x) for x in res]\n"
        "        return json.dumps({\"status\": \"success\", \"result\": out}, ensure_ascii=False, default=str)\n"
        "    except Exception as e:\n"
        "        return json.dumps({\"status\": \"error\", \"message\": str(e)[:300]}, ensure_ascii=False)\n"
    )
    # сохранить прокси через аккаунт-токен устройства
    def _acct():
        # config.json Визарда — валидный токен+agent приоритетно; ~/.extella/api_token.txt — фолбэк
        cfg = os.path.expanduser("~/extella_wizard/app/config.json")
        if os.path.exists(cfg):
            try:
                d = json.load(open(cfg)); t = d.get("auth_token", "")
                if t: return t, d.get("agent_id", "")
            except Exception: pass
        pp = os.path.expanduser("~/.extella/api_token.txt")
        if os.path.exists(pp):
            t = open(pp).read().strip()
            if t: return t, ""
        return "", ""
    at, aid = _acct()
    if not at:
        return err("не найден аккаунт-токен устройства (config.json / ~/.extella/api_token.txt)")
    def api(path, body):
        h = {"X-Auth-Token": at, "X-Profile-Id": "default", "Content-Type": "application/json"}
        if aid: h["X-Agent-Id"] = aid
        rq = urllib.request.Request("https://api.extella.ai" + path, data=json.dumps(body).encode(), headers=h)
        return json.load(urllib.request.urlopen(rq, timeout=45))
    try:
        r = api("/api/expert/save", {"name": proxy, "description": "HF proxy " + space,
                                     "code": proxy_code, "kwargs": {}, "cspl": "fython", "global": True})
        if r.get("status") != "success":
            return err("прокси-эксперт не сохранён: " + str(r)[:120])
    except Exception as e:
        return err("прокси-эксперт не сохранён: " + str(e)[:120])

    # 3) index.html (панель: поле на параметр + файл + Run, зовёт прокси через мост)
    def esc(s): return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")
    inputs_html = ""
    js_collect = "var a=[];"
    for f in fields:
        if f["file"]: continue
        dv = "" if f["default"] is None else esc(f["default"])
        inputs_html += '<label>%s<input class="fin" data-i="%d" data-t="%s" value="%s"/></label>' % (esc(f["label"]), f["i"], f["type"], dv)
    js_collect = (
        "var ins=[].slice.call(document.querySelectorAll('.fin'));"
        "ins.sort(function(x,y){return (+x.dataset.i)-(+y.dataset.i)});"
        "var a=ins.map(function(el){var t=el.dataset.t,v=el.value;"
        "if(t.indexOf('float')>=0||t.indexOf('int')>=0)return v===''?0:Number(v);"
        "if(t.indexOf('bool')>=0)return v==='true'||v==='1';return v;});"
    )
    file_html = '<label>Файл<input type="file" id="ffile"/></label>' if has_file else ""
    idx = ("<!doctype html><meta charset=utf-8><title>%s</title>" % esc(display_name) +
        "<style>body{font-family:system-ui;max-width:640px;margin:24px auto;padding:0 16px;color:#1b1a16}"
        "h2{font-weight:700}label{display:block;margin:10px 0;font-size:13px;color:#5b5750}"
        "input{width:100%;box-sizing:border-box;padding:9px 11px;border:1px solid #ddd;border-radius:8px;margin-top:4px}"
        "button{background:#C67E34;color:#fff;border:0;border-radius:8px;padding:10px 18px;font-weight:700;cursor:pointer;margin-top:12px}"
        "pre{background:#f5f2ec;border-radius:8px;padding:12px;white-space:pre-wrap;word-break:break-word;margin-top:14px}</style>" +
        "<h2>%s</h2><div style='color:#8c877d;font-size:12px'>HF Space: %s</div>" % (esc(display_name), esc(space)) +
        inputs_html + file_html +
        "<button id=run>Запустить</button><pre id=out></pre>" +
        "<script>var PROXY=%r;" % proxy +
        "function call(params){return new Promise(function(res){var id='r'+Date.now();"
        "function on(e){if(e.data&&e.data.type==='etb_expert_result'&&e.data.reqId===id){window.removeEventListener('message',on);res(e.data);}}"
        "window.addEventListener('message',on);"
        "window.parent.postMessage({type:'etb_run_expert',reqId:id,name:PROXY,params:params},'*');});}"
        "document.getElementById('run').onclick=function(){var out=document.getElementById('out');out.textContent='Запускаю…';"
        + js_collect +
        "function go(fb){call({args_json:JSON.stringify(a),file_b64:fb||''}).then(function(r){var o=r.res;"
        "if(o&&o.result!==undefined)o=o.result;else if(o&&o.res)o=o.res;out.textContent=typeof o==='string'?o:JSON.stringify(o,null,2);})"
        ".catch(function(){out.textContent='Ошибка вызова';});}"
        "var ff=document.getElementById('ffile');"
        "if(ff&&ff.files&&ff.files[0]){var rd=new FileReader();rd.onload=function(){go(rd.result);};rd.readAsDataURL(ff.files[0]);}else{go('');}"
        "};</script>")
    try:
        os.makedirs(root_path, exist_ok=True)
        os.makedirs(os.path.dirname(registry_path), exist_ok=True)
        open(os.path.join(root_path, "index.html"), "w", encoding="utf-8").write(idx)
    except Exception as e:
        return err("index.html не записан: " + str(e)[:100])

    # 4) сервер + стартовый эксперт + реестр
    try:
        subprocess.Popen([sys.executable, "-m", "http.server", port], cwd=root_path,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        open(os.path.join(root_path, "server.pid"), "w").write("started")
    except Exception:
        pass
    start_code = ("# expert: %s\n# description: старт сервера плагина %s\n" % (start_expert, plugin_id) +
        "def %s():\n    import subprocess,sys,os,json\n    rp=%r\n" % (start_expert, root_path) +
        "    subprocess.Popen([sys.executable,'-m','http.server',%r],cwd=rp,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n" % port +
        "    return json.dumps({'status':'ok','port':%r})\n" % port)
    try:
        api("/api/expert/save", {"name": start_expert, "description": "start " + plugin_id,
                                 "code": start_code, "kwargs": {}, "cspl": "fython", "global": True})
    except Exception: pass
    manifest = {"id": plugin_id, "name": display_name, "type": "github", "mode": "generated_ui",
                "hf": {"id": space, "kind": "space", "hosted": True},
                "ui": {"type": "local_server", "port": int(port), "rootPath": root_path,
                       "startExpert": start_expert, "mainFile": "index.html", "openInBrowser": False, "expectsHealth": False},
                "service": {"isApp": False, "port": int(port), "startExpert": start_expert, "ready": True},
                "experts": [proxy], "installed": True}
    try:
        open(registry_path, "w", encoding="utf-8").write(json.dumps(manifest, ensure_ascii=False, indent=2))
    except Exception as e:
        return err("реестр не записан: " + str(e)[:100])
    return json.dumps({"status": "success", "plugin_id": plugin_id, "proxy": proxy,
                       "endpoint": api_name, "params": len(fields), "port": port,
                       "ok": True, "message": "установлено детерминированно"}, ensure_ascii=False)
