#!/usr/bin/env python3
"""Конвертер Pinokio-рецепта → формат Extella (.extella.json). ОФЛАЙН у нас на сборке.
Использует песочный recipe_resolve.js (безопасно исполняет чужой JS) → плоские шаги →
маппит в декларативный JSON. Клиент потом ставит нашим чистым Python-раннером recipe_x.
Запуск: python3 pinokio_to_extella.py <app_dir> <id> <git_url>"""
import os, sys, json, subprocess

RESOLVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recipe_resolve.js")

def _resolve(app_dir, entry):
    if not os.path.isfile(os.path.join(app_dir, entry)):
        return {"steps": [], "port": None, "daemon": False}
    r = subprocess.run(["node", RESOLVER, app_dir, entry, "", "", ""],
                       capture_output=True, text=True, timeout=60)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"steps": [], "port": None, "daemon": False, "errors": [r.stderr[-200:]]}

def _steps_to_x(steps):
    out = []
    for s in steps:
        if s.get("method") != "shell.run":
            continue
        p = s.get("params", {})
        msgs = p.get("message") or []
        for m in msgs:
            step = {"run": m}
            if p.get("path"): step["cwd"] = p["path"]
            if p.get("venv"): step["venv"] = p["venv"]
            if p.get("env"):
                # порт → плейсхолдер нашего формата
                env = {}
                for k, v in p["env"].items():
                    env[k] = "{{port}}" if str(v).isdigit() else v
                step["env"] = env
            out.append(step)
    return out

def convert(app_dir, rid, git_url):
    inst = _resolve(app_dir, "install.js")
    strt = _resolve(app_dir, "start.js")
    recipe = {
        "id": rid,
        "name": rid,
        "kind": "app",
        "source": {"git": git_url},
        "requires": ["git", "node"],
        "install": _steps_to_x(inst.get("steps", [])),
    }
    start_steps = _steps_to_x(strt.get("steps", []))
    if start_steps:
        s0 = start_steps[0]
        start = {"run": s0["run"], "daemon": bool(strt.get("daemon")),
                 "ready": {"log": "https?://\\S+"}}
        for k in ("cwd", "venv", "env"):
            if k in s0: start[k] = s0[k]
        recipe["start"] = start
    return recipe

if __name__ == "__main__":
    app_dir, rid, git_url = sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else ""
    print(json.dumps(convert(app_dir, rid, git_url), ensure_ascii=False, indent=2))
