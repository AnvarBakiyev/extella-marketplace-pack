# expert: cap_graphviz_to_png_batch
# description: Схемы из текста — Рисует диаграммы и графы из .dot-описания — локально Пакетно: операция «Схема → PNG» ко всем подходящим файлам в папке. Локально/офлайн.

def cap_graphviz_to_png_batch(in_dir="", out_dir="", _pad=None) -> str:
    import os, subprocess, json, glob, shutil, tempfile

    def binpath():
        try:
            from extella_expert_bridge import path_or_error
            path, _state = path_or_error("graphviz", repair=False)
            return path
        except Exception:
            return None
    if not in_dir or in_dir.startswith("{{") or not os.path.isdir(in_dir):
        return json.dumps({"status":"error","message":"нужен существующий in_dir"}, ensure_ascii=False)
    pass
    b = binpath()
    if not b:
        return json.dumps({"status":"error","message":"Graphviz (схемы из текста) не установлен — сначала cap_graphviz_resolver(confirm_install='yes')"}, ensure_ascii=False)
    if not out_dir or out_dir.startswith("{{"): out_dir = in_dir.rstrip("/") + "_out"
    os.makedirs(out_dir, exist_ok=True)
    _env = dict(os.environ)
    pass
    srcs = sorted(glob.glob(os.path.join(in_dir, "*.dot")))
    tin = 0; tout = 0; ok = 0; fail = 0; items = []
    for src in srcs:
        stem = os.path.splitext(os.path.basename(src))[0]
        dst = os.path.join(out_dir, stem + ".png")
        before = os.path.getsize(src)
        pass
        TMPL = ["-Tpng", "{input}", "-o", "{output}"]
        SUB = {"input": src, "output": dst}
        argv = [b]
        for tok in TMPL:
            for k, v in SUB.items():
                tok = tok.replace("{" + k + "}", str(v))
            argv.append(tok)
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=120, env=_env)
            if r.returncode == 0 and os.path.exists(dst):
                after = os.path.getsize(dst)
                pass
                tin += before; tout += after; ok += 1
                items.append({"file": os.path.basename(src), "out_kb": round(after/1024,1)})
            else:
                fail += 1; items.append({"file": os.path.basename(src), "error": (r.stderr or "")[:60]})
        except Exception as e:
            fail += 1; items.append({"file": os.path.basename(src), "error": str(e)[:60]})
    saved = round(100*(tin-tout)/tin, 1) if tin else 0
    return json.dumps({"status":"success","count":len(srcs),"ok":ok,"failed":fail,"total_saved_pct":saved,"in_mb":round(tin/1048576,2),"out_mb":round(tout/1048576,2),"out_dir":out_dir,"items":items[:20]}, ensure_ascii=False)