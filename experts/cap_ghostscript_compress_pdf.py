# expert: cap_ghostscript_compress_pdf
# description: Сжать PDF — Ужать PDF на 50–70% — локально, файлы не уходят Операция «Сжать PDF», один файл. Локально/офлайн. Зови ЭТОТ эксперт, НЕ пиши shell-команду.

def cap_ghostscript_compress_pdf(input_path="", output_path="", quality="ebook") -> str:
    import os, subprocess, json, shutil, tempfile
    ALLOWED_quality = ('screen', 'ebook', 'printer', 'prepress')
    def binpath():
        try:
            from extella_expert_bridge import path_or_error
            path, _state = path_or_error("ghostscript", repair=False)
            return path
        except Exception:
            return None
    if not input_path or input_path.startswith("{{") or not os.path.exists(input_path):
        return json.dumps({"status":"error","message":"нужен существующий input_path"}, ensure_ascii=False)
    if not quality or quality.startswith("{{") or quality not in ALLOWED_quality: quality = "ebook"
    b = binpath()
    if not b:
        return json.dumps({"status":"error","message":"Ghostscript (сжатие PDF) не установлен — сначала cap_ghostscript_resolver(confirm_install='yes')"}, ensure_ascii=False)
    if not output_path or output_path.startswith("{{"):
        base, _ = os.path.splitext(input_path); output_path = base + "_compressed.pdf"
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    before = os.path.getsize(input_path)
    TMPL = ["-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4", "-dPDFSETTINGS=/{quality}", "-dNOPAUSE", "-dBATCH", "-dQUIET", "-dSAFER", "-sOutputFile={output}", "{input}"]
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