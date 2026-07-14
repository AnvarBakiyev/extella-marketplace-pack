# expert: wz_extract_doc_b64
# description: Извлекает текст из файла (base64): PDF (pdftotext ИЛИ python pypdf/pdfminer), Word .docx (pandoc ИЛИ python docx2txt), txt/html/rtf/odt. Без обязательных системных CLI — python-фолбэк ставится сам. Для приложения документа в окнах плагинов. {status,name,text}.
def wz_extract_doc_b64(b64="", name="doc"):
    import os, base64, tempfile, subprocess, json, shutil, re
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
    def pdf_py(path):
        # чистый python, без системного pdftotext
        try:
            include("import pypdf", ["extella-pip install pypdf"])
            rd = pypdf.PdfReader(path)
            return "\n".join((pg.extract_text() or "") for pg in rd.pages)
        except Exception:
            pass
        try:
            include("from pdfminer.high_level import extract_text", ["extella-pip install pdfminer.six"])
            return extract_text(path)
        except Exception:
            return None
    def docx_py(path):
        try:
            include("import docx2txt", ["extella-pip install docx2txt"])
            return docx2txt.process(path) or ""
        except Exception:
            return None
    LIM = 200000
    try:
        if ext == ".pdf":
            b = which("pdftotext")
            if b:
                r = subprocess.run([b, "-layout", p, "-"], capture_output=True, text=True, timeout=120)
                txt = r.stdout or ""
            else:
                txt = pdf_py(p)
                if txt is None:
                    return json.dumps({"status": "error", "message": "не смог прочитать PDF (нет pdftotext и не встал python-извлекатель)"}, ensure_ascii=False)
        elif ext == ".docx":
            b = which("pandoc")
            if b:
                r = subprocess.run([b, p, "-t", "plain"], capture_output=True, text=True, timeout=120); txt = r.stdout or ""
            else:
                txt = docx_py(p)
                if txt is None:
                    return json.dumps({"status": "error", "message": "не смог прочитать Word (нет pandoc и не встал python-извлекатель)"}, ensure_ascii=False)
        elif ext in (".html", ".htm"):
            b = which("pandoc")
            if b:
                r = subprocess.run([b, p, "-t", "plain"], capture_output=True, text=True, timeout=120); txt = r.stdout or ""
            else:
                html = open(p, encoding="utf-8", errors="replace").read()
                txt = re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html))
                txt = re.sub(r"[ \t]+", " ", txt)
        elif ext in (".doc", ".odt", ".rtf", ".epub"):
            b = which("pandoc")
            if not b:
                return json.dumps({"status": "error", "message": "для " + ext + " нужен pandoc — поставь «Документы Word» (или пришли .pdf/.docx/.txt)"}, ensure_ascii=False)
            r = subprocess.run([b, p, "-t", "plain"], capture_output=True, text=True, timeout=120); txt = r.stdout or ""
        else:
            txt = open(p, encoding="utf-8", errors="replace").read()
        return json.dumps({"status": "success", "name": nm, "text": (txt or "")[:LIM]}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)[:200]}, ensure_ascii=False)
    finally:
        try: shutil.rmtree(d, ignore_errors=True)
        except Exception: pass
