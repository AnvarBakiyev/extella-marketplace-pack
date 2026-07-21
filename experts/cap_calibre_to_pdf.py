# expert: cap_calibre_to_pdf
# description: Конвертер книг — EPUB, MOBI, PDF, FB2 — конвертация электронных книг, локально Операция «В PDF», один файл. Локально/офлайн. Зови ЭТОТ эксперт, НЕ пиши shell-команду.

def cap_calibre_to_pdf(input_path="", output_path="") -> str:
    import os, subprocess, json, shutil, tempfile

    def binpath():
        try:
            from extella_expert_bridge import path_or_error
            path, _state = path_or_error("calibre", repair=False)
            return path
        except Exception:
            return None
    if not input_path or input_path.startswith("{{") or not os.path.exists(input_path):
        return json.dumps({"status":"error","message":"нужен существующий input_path"}, ensure_ascii=False)
    pass
    b = binpath()
    if not b:
        return json.dumps({"status":"error","message":"Calibre (конвертация книг) не установлен — сначала cap_calibre_resolver(confirm_install='yes')"}, ensure_ascii=False)
    if not output_path or output_path.startswith("{{"):
        base, _ = os.path.splitext(input_path); output_path = base + ".pdf"
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    before = os.path.getsize(input_path)
    TMPL = ["{input}", "{output}"]
    SUB = {"input": input_path, "output": output_path}
    argv = [b]
    for tok in TMPL:
        for k, v in SUB.items():
            tok = tok.replace("{" + k + "}", str(v))
        argv.append(tok)
    _env = dict(os.environ)
    pass
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=300, env=_env)
    except Exception as e:
        return json.dumps({"status":"error","message":"вызов упал: " + str(e)[:100]}, ensure_ascii=False)
    if r.returncode != 0 or not os.path.exists(output_path):
        return json.dumps({"status":"error","message":"инструмент не создал файл","err":(r.stderr or "")[:140]}, ensure_ascii=False)
    after = os.path.getsize(output_path)
    pass
    return json.dumps({"status":"success","output_path":output_path,"in_kb":round(before/1024,1),"out_kb":round(after/1024,1)}, ensure_ascii=False)