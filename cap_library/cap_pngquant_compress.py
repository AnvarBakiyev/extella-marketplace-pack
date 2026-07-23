# expert: cap_pngquant_compress
# description: Сжать PNG — Ужимает PNG без видимой потери качества — пачкой, локально Операция «Сжать PNG», один файл. Локально/офлайн. Зови ЭТОТ эксперт, НЕ пиши shell-команду.

def cap_pngquant_compress(input_path="", output_path="", quality="65-80") -> str:
    import os, subprocess, json, shutil, tempfile
    ALLOWED_quality = ('50-70', '65-80', '80-95')
    def binpath():
        f = os.path.expanduser("~/.extella_cli/pngquant")
        if os.path.exists(f):
            p = open(f).read().strip()
            if p and os.path.exists(p): return p
        p = shutil.which("pngquant")
        if p: return p
        for c in ["/opt/homebrew/bin/pngquant", "/usr/local/bin/pngquant"]:
            if os.path.exists(c): return c
        return None
    if not input_path or input_path.startswith("{{") or not os.path.exists(input_path):
        return json.dumps({"status":"error","message":"нужен существующий input_path"}, ensure_ascii=False)
    if not quality or quality.startswith("{{") or quality not in ALLOWED_quality: quality = "65-80"
    b = binpath()
    if not b:
        return json.dumps({"status":"error","message":"pngquant (сжать PNG) не установлен — сначала cap_pngquant_resolver(confirm_install='yes')"}, ensure_ascii=False)
    if not output_path or output_path.startswith("{{"):
        base, _ = os.path.splitext(input_path); output_path = base + "_min.png"
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    before = os.path.getsize(input_path)
    TMPL = ["--quality={quality}", "--force", "--output", "{output}", "{input}"]
    SUB = {"input": input_path, "output": output_path, "quality": quality}
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