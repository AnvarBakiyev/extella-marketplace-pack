# expert: cap_oxipng_optimize
# description: PNG без потерь — Ужимает PNG без потери качества (lossless) — пачкой, локально Операция «Сжать PNG без потерь», один файл. Локально/офлайн. Зови ЭТОТ эксперт, НЕ пиши shell-команду.

def cap_oxipng_optimize(input_path="", output_path="") -> str:
    import os, subprocess, json, shutil, tempfile

    def binpath():
        f = os.path.expanduser("~/.extella_cli/oxipng")
        if os.path.exists(f):
            p = open(f).read().strip()
            if p and os.path.exists(p): return p
        p = shutil.which("oxipng")
        if p: return p
        for c in ["/opt/homebrew/bin/oxipng", "/usr/local/bin/oxipng"]:
            if os.path.exists(c): return c
        return None
    if not input_path or input_path.startswith("{{") or not os.path.exists(input_path):
        return json.dumps({"status":"error","message":"нужен существующий input_path"}, ensure_ascii=False)
    pass
    b = binpath()
    if not b:
        return json.dumps({"status":"error","message":"oxipng (сжать PNG без потерь) не установлен — сначала cap_oxipng_resolver(confirm_install='yes')"}, ensure_ascii=False)
    if not output_path or output_path.startswith("{{"):
        base, _ = os.path.splitext(input_path); output_path = base + "_opt.png"
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    before = os.path.getsize(input_path)
    TMPL = ["-o", "4", "--out", "{output}", "{input}"]
    SUB = {"input": input_path, "output": output_path}
    argv = [b]
    for tok in TMPL:
        for k, v in SUB.items():
            tok = tok.replace("{" + k + "}", str(v))
        argv.append(tok)
    _env = dict(os.environ)
    pass
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=180, env=_env)
    except Exception as e:
        return json.dumps({"status":"error","message":"вызов упал: " + str(e)[:100]}, ensure_ascii=False)
    if r.returncode != 0 or not os.path.exists(output_path):
        return json.dumps({"status":"error","message":"инструмент не создал файл","err":(r.stderr or "")[:140]}, ensure_ascii=False)
    after = os.path.getsize(output_path)
    if after >= before:
        shutil.copyfile(input_path, output_path); after = before
    return json.dumps({"status":"success","output_path":output_path,"in_kb":round(before/1024,1),"out_kb":round(after/1024,1),"saved_pct":round(100*(before-after)/before,1) if before else 0}, ensure_ascii=False)