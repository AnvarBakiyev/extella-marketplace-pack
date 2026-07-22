# expert: wz_extract_doc
# description: Извлекает текст из одного файла по пути (PDF/Word/txt). Возвращает {status,name,text}.

def wz_extract_doc(path=""):
    import os, subprocess, json
    p = (path or "").strip()
    if not p or p.startswith("{{") or not os.path.isfile(p):
        return json.dumps({"status": "error", "message": "файл не найден: " + p}, ensure_ascii=False)
    ext = os.path.splitext(p)[1].lower()
    def which(x):
        try:
            from extella_expert_bridge import path_or_error
            path, _state = path_or_error(x, repair=False)
            return path
        except Exception:
            return None
    LIM = 200000
    try:
        if ext == ".pdf":
            b = which("pdftotext")
            if not b:
                return json.dumps({"status": "error", "message": "pdftotext не установлен — поставь инструмент «Текст из PDF»"}, ensure_ascii=False)
            r = subprocess.run([b, "-layout", p, "-"], capture_output=True, text=True, timeout=120)
            return json.dumps({"status": "success", "name": os.path.basename(p), "text": (r.stdout or "")[:LIM]}, ensure_ascii=False)
        if ext in (".docx", ".doc", ".odt", ".rtf", ".html", ".htm", ".epub"):
            b = which("pandoc")
            if not b:
                return json.dumps({"status": "error", "message": "pandoc не установлен — поставь инструмент «Документы Word»"}, ensure_ascii=False)
            r = subprocess.run([b, p, "-t", "plain"], capture_output=True, text=True, timeout=120)
            return json.dumps({"status": "success", "name": os.path.basename(p), "text": (r.stdout or "")[:LIM]}, ensure_ascii=False)
        txt = open(p, encoding="utf-8", errors="replace").read()
        return json.dumps({"status": "success", "name": os.path.basename(p), "text": txt[:LIM]}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)[:200]}, ensure_ascii=False)
