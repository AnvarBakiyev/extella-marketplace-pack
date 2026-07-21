# expert: cap_gifsicle_optimize
# description: Сжать GIF — Оптимизирует и уменьшает GIF-анимации — пачкой, локально Операция «Оптимизировать GIF», один файл. Локально/офлайн. Зови ЭТОТ эксперт, НЕ пиши shell-команду.

def cap_gifsicle_optimize(input_path="", output_path="") -> str:
    import os, subprocess, json, shutil, tempfile

    def binpath():
        try:
            from extella_expert_bridge import path_or_error
            path, _state = path_or_error("gifsicle", repair=False)
            return path
        except Exception:
            return None
    if not input_path or input_path.startswith("{{") or not os.path.exists(input_path):
        return json.dumps({"status":"error","message":"нужен существующий input_path"}, ensure_ascii=False)
    pass
    b = binpath()
    if not b:
        return json.dumps({"status":"error","message":"Gifsicle (оптимизация GIF) не установлен — сначала cap_gifsicle_resolver(confirm_install='yes')"}, ensure_ascii=False)
    if not output_path or output_path.startswith("{{"):
        base, _ = os.path.splitext(input_path); output_path = base + "_opt.gif"
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    before = os.path.getsize(input_path)
    TMPL = ["-O3", "{input}", "-o", "{output}"]
    SUB = {"input": input_path, "output": output_path}
    argv = [b]
    for tok in TMPL:
        for k, v in SUB.items():
            tok = tok.replace("{" + k + "}", str(v))
        argv.append(tok)
    _env = dict(os.environ)
    pass
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=120, env=_env)
    except Exception as e:
        return json.dumps({"status":"error","message":"вызов упал: " + str(e)[:100]}, ensure_ascii=False)
    if r.returncode != 0 or not os.path.exists(output_path):
        return json.dumps({"status":"error","message":"инструмент не создал файл","err":(r.stderr or "")[:140]}, ensure_ascii=False)
    after = os.path.getsize(output_path)
    if after >= before:
        shutil.copyfile(input_path, output_path); after = before
    return json.dumps({"status":"success","output_path":output_path,"in_kb":round(before/1024,1),"out_kb":round(after/1024,1),"saved_pct":round(100*(before-after)/before,1) if before else 0}, ensure_ascii=False)