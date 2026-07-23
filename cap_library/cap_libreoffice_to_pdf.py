# expert: cap_libreoffice_to_pdf
# description: Office → PDF — Word, Excel, PowerPoint → PDF целыми папками Операция «Office → PDF», один файл. Локально/офлайн. Зови ЭТОТ эксперт, НЕ пиши shell-команду.

def cap_libreoffice_to_pdf(input_path="", output_path="") -> str:
    import os, subprocess, json, shutil, tempfile

    def binpath():
        f = os.path.expanduser("~/.extella_cli/libreoffice")
        if os.path.exists(f):
            p = open(f).read().strip()
            if p and os.path.exists(p): return p
        p = shutil.which("soffice")
        if p: return p
        for c in ["/Applications/LibreOffice.app/Contents/MacOS/soffice", "/opt/homebrew/bin/soffice", "/usr/bin/soffice"]:
            if os.path.exists(c): return c
        return None
    if not input_path or input_path.startswith("{{") or not os.path.exists(input_path):
        return json.dumps({"status":"error","message":"нужен существующий input_path"}, ensure_ascii=False)
    pass
    b = binpath()
    if not b:
        return json.dumps({"status":"error","message":"LibreOffice (Office → PDF) не установлен — сначала cap_libreoffice_resolver(confirm_install='yes')"}, ensure_ascii=False)
    _inbase = os.path.splitext(os.path.basename(input_path))[0]
    _outdir = (os.path.dirname(os.path.abspath(output_path)) if output_path and not output_path.startswith("{{") else os.path.dirname(os.path.abspath(input_path))) or "."
    os.makedirs(_outdir, exist_ok=True)
    output_path = os.path.join(_outdir, _inbase + ".pdf")
    _profile = tempfile.mkdtemp(prefix="_locap_")
    before = os.path.getsize(input_path)
    TMPL = ["--headless", "--convert-to", "pdf", "--outdir", "{outdir}", "-env:UserInstallation=file://{profile}", "{input}"]
    SUB = {"input": input_path, "output": output_path, "outdir": _outdir, "profile": _profile}
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
    pass
    return json.dumps({"status":"success","output_path":output_path,"in_kb":round(before/1024,1),"out_kb":round(after/1024,1)}, ensure_ascii=False)