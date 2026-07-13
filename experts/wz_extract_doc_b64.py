# expert: wz_extract_doc_b64
# description: Извлекает текст из файла (base64): PDF→pdftotext, Word/rtf/odt→pandoc, txt→read. Для приложения документа в окнах плагинов. Возвращает {status,name,text}.

def wz_extract_doc_b64(b64="", name="doc"):
    import os, base64, tempfile, subprocess, json, shutil
    data = b64 or ""
    if "," in data[:64] and data[:5] in ("data:",): data = data.split(",", 1)[1]
    if not data:
        return json.dumps({"status": "error", "message": "пустые данные"}, ensure_ascii=False)
    nm = os.path.basename(name or "doc")
    ext = os.path.splitext(nm)[1].lower() or ".bin"
    try:
        raw = base64.b64decode(data)
    except Exception as e:
        return json.dumps({"status": "error", "message": "base64: " + str(e)[:60]}, ensure_ascii=False)
    if len(raw) > 12 * 1024 * 1024:
        return json.dumps({"status": "error", "message": "файл больше 12 МБ"}, ensure_ascii=False)
    d = tempfile.mkdtemp(prefix="extella_doc_")
    p = os.path.join(d, "in" + ext)
    open(p, "wb").write(raw)
    def which(x):
        w = shutil.which(x)
        if w: return w
        c = os.path.expanduser("~/.extella_cli/" + x)
        if os.path.exists(c):
            try:
                pth = open(c).read().strip()
                if pth and os.path.exists(pth): return pth
            except Exception: pass
        return None
    LIM = 200000
    try:
        if ext == ".pdf":
            b = which("pdftotext")
            if not b: return json.dumps({"status": "error", "message": "pdftotext не установлен — поставь «Текст из PDF»"}, ensure_ascii=False)
            r = subprocess.run([b, "-layout", p, "-"], capture_output=True, text=True, timeout=120)
            txt = r.stdout or ""
        elif ext in (".docx", ".doc", ".odt", ".rtf", ".html", ".htm", ".epub"):
            b = which("pandoc")
            if not b: return json.dumps({"status": "error", "message": "pandoc не установлен — поставь «Документы Word»"}, ensure_ascii=False)
            r = subprocess.run([b, p, "-t", "plain"], capture_output=True, text=True, timeout=120)
            txt = r.stdout or ""
        else:
            txt = open(p, encoding="utf-8", errors="replace").read()
        return json.dumps({"status": "success", "name": nm, "text": txt[:LIM]}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)[:200]}, ensure_ascii=False)
    finally:
        try: shutil.rmtree(d, ignore_errors=True)
        except Exception: pass
