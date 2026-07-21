# expert: cap_ocr_searchable
# description: Поиск по сканам (OCR) — Сканы и фото-PDF → документы с полнотекстовым поиском Операция «Скан → PDF с поиском», один файл. Локально/офлайн. Зови ЭТОТ эксперт, НЕ пиши shell-команду.

def cap_ocr_searchable(input_path="", output_path="", lang="rus+eng") -> str:
    import os, subprocess, json, shutil, tempfile
    ALLOWED_lang = ('rus+eng', 'rus', 'eng')
    def binpath():
        try:
            from extella_expert_bridge import path_or_error
            path, _state = path_or_error("ocrmypdf", repair=False)
            return path
        except Exception:
            return None
    if not input_path or input_path.startswith("{{") or not os.path.exists(input_path):
        return json.dumps({"status":"error","message":"нужен существующий input_path"}, ensure_ascii=False)
    if not lang or lang.startswith("{{") or lang not in ALLOWED_lang: lang = "rus+eng"
    b = binpath()
    if not b:
        return json.dumps({"status":"error","message":"OCR (поиск по сканам) не установлен — сначала cap_ocr_resolver(confirm_install='yes')"}, ensure_ascii=False)
    if not output_path or output_path.startswith("{{"):
        base, _ = os.path.splitext(input_path); output_path = base + "_ocr.pdf"
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    before = os.path.getsize(input_path)
    TMPL = ["-l", "{lang}", "--skip-text", "--output-type", "pdf", "{input}", "{output}"]
    SUB = {"input": input_path, "output": output_path, "lang": lang}
    argv = [b]
    for tok in TMPL:
        for k, v in SUB.items():
            tok = tok.replace("{" + k + "}", str(v))
        argv.append(tok)
    _env = dict(os.environ)
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=300, env=_env)
    except Exception as e:
        return json.dumps({"status":"error","message":"вызов упал: " + str(e)[:100]}, ensure_ascii=False)
    if r.returncode != 0 or not os.path.exists(output_path):
        return json.dumps({"status":"error","message":"инструмент не создал файл","err":(r.stderr or "")[:140]}, ensure_ascii=False)
    after = os.path.getsize(output_path)
    pass
    return json.dumps({"status":"success","output_path":output_path,"in_kb":round(before/1024,1),"out_kb":round(after/1024,1)}, ensure_ascii=False)