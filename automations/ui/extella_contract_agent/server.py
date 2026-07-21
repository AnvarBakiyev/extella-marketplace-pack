#!/usr/bin/env python3
"""Extella Contract Agent — onboarding bridge (localhost:8767).

Маршруты: / и /onboarding.html — панель; /x/* — JSON API; /out/<file> — готовые документы.
Секреты живут в ~/extella_wizard/app/config.json (auth_token, telegram_bot_token, telegram_chat_id).
Сервер локальный (127.0.0.1), наружу ничего не открывает. Отправку писем/сообщений делает ЧЕЛОВЕК."""
import json, os, ssl, time, io, base64, subprocess, threading, uuid, urllib.request, urllib.error, mimetypes
from urllib.parse import unquote, quote
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROGRESS = {}  # job_id -> {step, index, total, done, error, result}

PORT = 8767
HERE = os.path.dirname(os.path.abspath(__file__))
WIZARD_ROOT = os.environ.get("EXTELLA_WIZARD_ROOT") or os.path.expanduser("~/extella_wizard")
PLUGIN_ROOT = os.environ.get("EXTELLA_PLUGIN_ROOT") or os.path.expanduser("~/extella-plugins")
CFG_PATH = os.path.join(WIZARD_ROOT, "app", "config.json")
OUT_DIR = os.path.join(PLUGIN_ROOT, "extella_contract_agent", "out")
os.makedirs(OUT_DIR, exist_ok=True)
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE


def cfg():
    try:
        return json.load(open(CFG_PATH, encoding="utf-8"))
    except Exception:
        return {}


def cfg_save(patch):
    c = cfg(); c.update(patch)
    os.makedirs(os.path.dirname(CFG_PATH), exist_ok=True)
    json.dump(c, open(CFG_PATH, "w", encoding="utf-8"), ensure_ascii=False)
    return c


def xapi(path, payload, timeout=120):
    c = cfg()
    req = urllib.request.Request("https://api.extella.ai" + path, data=json.dumps(payload).encode("utf-8"),
                                 headers={"X-Auth-Token": c.get("auth_token", ""), "Content-Type": "application/json",
                                          "X-Profile-Id": "default",
                                          "X-Agent-Id": c.get("agent_id", "agent_extella_alibaba_default")}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return json.loads(r.read().decode("utf-8"))


def run_expert(name, params, timeout=600):
    """Run expert with deferred-task polling; returns parsed dict/str."""
    out = xapi("/api/expert/run", {"expert_name": name, "params": params, "global": True}, timeout)
    if isinstance(out, dict) and out.get("task_id") and "deferred" in str(out.get("result", "")).lower():
        tid = out["task_id"]; waited = 0
        while waited < timeout:
            time.sleep(4); waited += 4
            try:
                st = xapi("/api/tasks/check", {"task_id": tid}, 30)
            except Exception:
                continue
            if str(st.get("status", "")).lower() in ("completed", "success", "done", "error", "failed"):
                out = st; break
    res = out.get("result", out) if isinstance(out, dict) else out
    if isinstance(res, str):
        try: res = json.loads(res)
        except Exception:
            import ast
            try: res = ast.literal_eval(res)
            except Exception: res = {"raw": res}
    return res


def _docx_text(raw):
    """Извлечь текст из .docx (zip → document.xml) без внешних зависимостей."""
    import zipfile, re
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        xml = z.read("word/document.xml").decode("utf-8", "replace")
        xml = re.sub(r"</w:p>", "\n", xml)
        xml = re.sub(r"<[^>]+>", "", xml)
        import html as _html
        return _html.unescape(xml).strip()
    except Exception:
        return ""


# ── handlers ──
def h_status(_):
    c = cfg()
    st = {"token": bool(c.get("auth_token")),
          "telegram": bool(c.get("telegram_bot_token") and c.get("telegram_chat_id")),
          "email": bool(c.get("smtp_host") and c.get("smtp_user") and c.get("smtp_pass")),
          "email_from": c.get("email_from") or c.get("smtp_user") or "",
          "whatsapp": False,
          "standards": c.get("contract_standards") or {},
          "parties": c.get("contract_parties") or {},
          "policies": [{"name": p.get("name", ""), "chars": len(str(p.get("text", "")))}
                       for p in (c.get("company_policies") or []) if isinstance(p, dict)],
          "clients": c.get("contract_clients") or [],
          "gk": False}
    if c.get("greenapi_id") and c.get("greenapi_token"):
        try:
            r = run_expert("lp_wa_state", {}, 30)
            st["whatsapp"] = isinstance(r, dict) and bool(r.get("authorized"))
        except Exception:
            st["whatsapp"] = False
    # проверка базы знаний «Гражданский кодекс РК»
    try:
        r = run_expert("kp_ask", {"name": "Гражданский кодекс РК",
                                  "question": "Есть ли база? Ответь одним словом."}, 60)
        ans = (r or {}).get("answer", "") if isinstance(r, dict) else str(r)
        st["gk"] = bool(ans) and "база не найдена" not in str(ans).lower()
    except Exception:
        st["gk"] = False
    return st


def h_save_config(body):
    std = body.get("standards") or {}
    parties = body.get("parties") or {}
    cfg_save({"contract_standards": std, "contract_parties": parties})
    return {"status": "success", "standards": std, "parties": parties}


def h_save_telegram(body):
    tok = (body.get("bot_token") or "").strip()
    cid = (body.get("chat_id") or "").strip()
    if tok: cfg_save({"telegram_bot_token": tok})
    if cid: cfg_save({"telegram_chat_id": cid})
    r = run_expert("lp_notify", {"text": "✅ Extella «Юрист по договорам»: уведомления подключены. Сюда будут приходить сводки и черновики на согласование."}, 40)
    ok = isinstance(r, dict) and r.get("status") == "success"
    return {"status": "success" if ok else "error", "detail": r}


REVIEW_STEPS = ["Читаю договор",
                "Сверяю с чек-листом, стандартами и Гражданским кодексом",
                "Собираю реестр рисков и документы"]


def _do_review(jid, text, fname):
    def setp(i, **kw):
        PROGRESS[jid] = {"step": REVIEW_STEPS[i] if i < len(REVIEW_STEPS) else "Готово",
                         "index": i + 1, "total": len(REVIEW_STEPS), "done": False, "error": None, **kw}
    try:
        setp(0)
        inp = os.path.join(OUT_DIR, "contracts_in.json")
        json.dump([{"file": fname, "text": text}], open(inp, "w", encoding="utf-8"), ensure_ascii=False)
        eval_out = os.path.join(OUT_DIR, "analysis.json")
        # этап 2 — анализ (чек-лист + стандарты + ГК)
        setp(1)
        a = run_expert("p2d4_evaluate_contract_batch", {"input_path": inp, "output_path": eval_out}, 900)
        if not isinstance(a, dict) or a.get("status") == "error":
            PROGRESS[jid] = {"done": True, "error": "анализ не удался: " + str(a)[:200]}; return
        # этап 3 — документы
        setp(2)
        d = run_expert("p2d4_generate_document_package", {"input_path": eval_out, "output_dir": OUT_DIR}, 300)
        disputed = []
        try:
            adoc = json.loads(open(eval_out, encoding="utf-8").read())
            for rec in (adoc.get("records") or []):
                for dv in ((rec.get("ai_analysis") or {}).get("deviations") or []):
                    disputed.append({"clause": dv.get("condition", ""), "standard": dv.get("standard", ""),
                                     "our_ask": "привести к стандарту компании", "severity": dv.get("severity", "")})
        except Exception:
            disputed = []
        def bn(p): return os.path.basename(p) if p else ""
        result = {"status": "success",
                  "high_risk_contracts": a.get("high_risk_contracts", 0),
                  "gk_grounded": a.get("gk_grounded", False),
                  "bases_used": a.get("bases_used", []),
                  "disputed_points": disputed,
                  "docs": {"registry": bn((d or {}).get("registry_xlsx")),
                           "protocol": bn((d or {}).get("protocol_docx")),
                           "summary": bn((d or {}).get("summary_txt"))},
                  "analysis_path": eval_out}
        PROGRESS[jid] = {"step": "Готово", "index": len(REVIEW_STEPS), "total": len(REVIEW_STEPS),
                         "done": True, "error": None, "result": result}
    except Exception as e:
        PROGRESS[jid] = {"done": True, "error": str(e)[:200]}


def h_run_review(body):
    text = (body.get("contract_text") or "").strip()
    fname = (body.get("filename") or "Договор.txt").strip()
    b64 = body.get("file_b64") or ""
    if b64 and not text:
        try:
            raw = base64.b64decode(b64.split(",")[-1])
            text = _docx_text(raw) if fname.lower().endswith(".docx") else raw.decode("utf-8", "replace")
        except Exception as e:
            return {"status": "error", "message": "не смог прочитать файл: " + str(e)[:100]}
    if len(text) < 60:
        return {"status": "error", "message": "текст договора слишком короткий — вставьте текст или загрузите файл"}
    jid = uuid.uuid4().hex
    PROGRESS[jid] = {"step": "Запускаю", "index": 0, "total": len(REVIEW_STEPS), "done": False, "error": None}
    threading.Thread(target=_do_review, args=(jid, text, fname), daemon=True).start()
    return {"status": "started", "job_id": jid, "steps": REVIEW_STEPS}


def h_review_progress(body):
    p = PROGRESS.get(body.get("job_id"))
    if not p:
        return {"status": "error", "done": True, "error": "job not found"}
    # чистим завершённые старые задачи лениво
    if p.get("done"):
        return {"status": "success", **p}
    return {"status": "success", **p}


def h_negotiate(body):
    c = cfg()
    params = {"disputed_json": json.dumps(body.get("disputed_points") or [], ensure_ascii=False),
              "round_no": int(body.get("round_no") or 1),
              "counterparty_reply": body.get("counterparty_reply") or "",
              "our_side": (c.get("contract_parties") or {}).get("our_side", "") or body.get("our_side", ""),
              "counterparty": (c.get("contract_parties") or {}).get("counterparty", "") or body.get("counterparty", ""),
              "contract_subject": body.get("contract_subject", "договор поставки")}
    r = run_expert("p2d5_negotiate", params, 500)
    if not isinstance(r, dict) or r.get("status") == "error":
        return {"status": "error", "message": "не удалось подготовить письмо: " + str(r)[:200]}
    return {"status": "success", "draft_email": r.get("draft_email", {}), "points": r.get("points", []),
            "gk_grounded": r.get("gk_grounded", False), "round": r.get("round", 1)}


def h_notify(body):
    text = (body.get("text") or "").strip()
    if not text:
        return {"status": "error", "message": "пустой текст"}
    r = run_expert("lp_notify", {"text": text}, 40)
    ok = isinstance(r, dict) and r.get("status") == "success"
    return {"status": "success" if ok else "error", "detail": r}


def h_assist(body):
    q = (body.get("question") or "").strip()
    hist = (body.get("history") or "").strip()
    if not q:
        return {"status": "error", "answer": "Задайте вопрос."}
    r = run_expert("lp_assistant", {"question": q, "history": hist[:3000]}, 180)
    if isinstance(r, dict):
        return {"status": r.get("status", "success"), "answer": r.get("answer", ""),
                "action": r.get("action", "none"), "expert": r.get("expert", "")}
    return {"status": "success", "answer": str(r)[:1500], "action": "none", "expert": ""}


# ── каналы связи ──
def h_save_email(body):
    patch = {}
    for k in ("smtp_host", "smtp_port", "smtp_user", "smtp_pass", "email_from"):
        v = (body.get(k) or "").strip()
        if v: patch[k] = v
    if patch: cfg_save(patch)
    c = cfg()
    to = c.get("email_from") or c.get("smtp_user")
    r = run_expert("lp_email_send", {"to": to, "subject": "Extella — проверка почты",
                                     "body": "Это тестовое письмо от агента «Юрист по договорам». Почта подключена — агент сможет отправлять письма контрагентам и сводки."}, 60)
    ok = isinstance(r, dict) and r.get("status") == "success"
    return {"status": "success" if ok else "error", "detail": r, "test_to": to}


def h_save_whatsapp(body):
    for k, ck in (("id_instance", "greenapi_id"), ("api_token_instance", "greenapi_token")):
        v = (body.get(k) or "").strip()
        if v: cfg_save({ck: v})
    r = run_expert("lp_wa_state", {}, 40)
    return {"status": "success", "detail": r,
            "authorized": isinstance(r, dict) and bool(r.get("authorized"))}


def h_save_telegram2(body):
    return h_save_telegram(body)


# ── политики / стандарты (файлы) ──
def h_upload_policy(body):
    name = (body.get("filename") or "Политика").strip()
    text = (body.get("text") or "").strip()
    b64 = body.get("file_b64") or ""
    if b64 and not text:
        try:
            raw = base64.b64decode(b64.split(",")[-1])
            text = _docx_text(raw) if name.lower().endswith(".docx") else raw.decode("utf-8", "replace")
        except Exception as e:
            return {"status": "error", "message": "не смог прочитать файл: " + str(e)[:100]}
    if len(text) < 20:
        return {"status": "error", "message": "документ пустой или слишком короткий"}
    c = cfg()
    pol = c.get("company_policies") or []
    if not isinstance(pol, list): pol = []
    pol = [p for p in pol if isinstance(p, dict) and p.get("name") != name]
    pol.append({"name": name, "text": text[:12000]})
    cfg_save({"company_policies": pol})
    return {"status": "success", "policies": [{"name": p["name"], "chars": len(p["text"])} for p in pol]}


def h_clear_policies(_):
    cfg_save({"company_policies": []})
    return {"status": "success", "policies": []}


# ── клиенты / контрагенты ──
def h_clients(_):
    return {"status": "success", "clients": cfg().get("contract_clients") or []}


def h_add_client(body):
    c = cfg()
    lst = c.get("contract_clients") or []
    if not isinstance(lst, list): lst = []
    cl = {"name": (body.get("name") or "").strip(), "company": (body.get("company") or "").strip(),
          "email": (body.get("email") or "").strip(), "phone": (body.get("phone") or "").strip()}
    if not cl["name"] and not cl["email"] and not cl["phone"]:
        return {"status": "error", "message": "укажите хотя бы имя, почту или телефон"}
    lst = [x for x in lst if not (x.get("email") and x.get("email") == cl["email"] and cl["email"])]
    lst.append(cl)
    cfg_save({"contract_clients": lst})
    return {"status": "success", "clients": lst}


def h_upload_clients(body):
    import csv as _csv
    raw = body.get("csv") or ""
    b64 = body.get("file_b64") or ""
    if b64 and not raw:
        try: raw = base64.b64decode(b64.split(",")[-1]).decode("utf-8", "replace")
        except Exception as e: return {"status": "error", "message": str(e)[:100]}
    if not raw.strip():
        return {"status": "error", "message": "пустой CSV"}
    out = []
    try:
        rd = _csv.reader(io.StringIO(raw))
        rows = list(rd)
        start = 1 if rows and any(h.lower() in ("имя", "name", "почта", "email", "телефон", "phone") for h in rows[0]) else 0
        for row in rows[start:]:
            if not row: continue
            row = (row + ["", "", "", ""])[:4]
            out.append({"name": row[0].strip(), "email": row[1].strip(), "phone": row[2].strip(), "company": row[3].strip()})
    except Exception as e:
        return {"status": "error", "message": "не разобрал CSV: " + str(e)[:100]}
    cfg_save({"contract_clients": out})
    return {"status": "success", "clients": out}


# ── отправка (человек нажимает «Отправить») ──
def h_send_email(body):
    to = (body.get("to") or "").strip()
    if not to:
        return {"status": "error", "message": "не указан адрес получателя"}
    r = run_expert("lp_email_send", {"to": to, "subject": body.get("subject", ""), "body": body.get("body", ""),
                                     "cc": body.get("cc", "")}, 90)
    ok = isinstance(r, dict) and r.get("status") == "success"
    return {"status": "success" if ok else "error", "detail": r}


def h_send_wa(body):
    phone = (body.get("phone") or "").strip()
    if not phone:
        return {"status": "error", "message": "не указан телефон"}
    r = run_expert("lp_wa_send", {"phone": phone, "text": body.get("text", "")}, 60)
    ok = isinstance(r, dict) and r.get("status") == "success"
    return {"status": "success" if ok else "error", "detail": r}


LEGAL_CATALOG = ["Гражданский кодекс РК", "Налоговый кодекс РК", "Трудовой кодекс РК",
                 "Кодекс об административных правонарушениях РК", "Предпринимательский кодекс РК"]
KB_DIR = os.path.join(PLUGIN_ROOT, "extella_contract_agent", "kb")


def _kp_available(name):
    try:
        r = run_expert("kp_ask", {"name": name, "question": "Есть ли база? одно слово"}, 90)
        ans = (r or {}).get("answer", "") if isinstance(r, dict) else str(r)
        return bool(ans) and "не найден" not in str(ans).lower()
    except Exception:
        return False


def h_kb_status(_):
    c = cfg()
    legal = c.get("legal_bases") or ["Гражданский кодекс РК"]
    cat = [{"name": n, "connected": n in legal} for n in LEGAL_CATALOG]
    for n in legal:
        if n not in LEGAL_CATALOG:
            cat.append({"name": n, "connected": True})
    return {"status": "success", "legal": cat, "knowledge_bases": c.get("knowledge_bases") or []}


def h_kb_add_legal(body):
    name = (body.get("name") or "").strip()
    if not name:
        return {"status": "error", "message": "не указано название базы"}
    if not _kp_available(name):
        return {"status": "error", "available": False,
                "message": "Эта база пока не установлена в Extella. Установите её в разделе «Базы знаний» приложения, затем подключите здесь."}
    c = cfg(); legal = c.get("legal_bases") or ["Гражданский кодекс РК"]
    if name not in legal:
        legal.append(name); cfg_save({"legal_bases": legal})
    return {"status": "success", "legal_bases": legal}


def h_kb_remove_legal(body):
    name = (body.get("name") or "").strip()
    c = cfg(); legal = [n for n in (c.get("legal_bases") or ["Гражданский кодекс РК"]) if n != name]
    if not legal:
        legal = ["Гражданский кодекс РК"]
    cfg_save({"legal_bases": legal})
    return {"status": "success", "legal_bases": legal}


def h_kb_create(body):
    name = (body.get("name") or "").strip()
    files = body.get("files") or []
    if not name:
        return {"status": "error", "message": "укажите название базы"}
    if not files:
        return {"status": "error", "message": "добавьте хотя бы один документ"}
    safe = "".join(ch if ch.isalnum() or ch in " _-" else "_" for ch in name).strip()[:60] or "base"
    folder = os.path.join(KB_DIR, safe)
    os.makedirs(folder, exist_ok=True)
    saved = 0
    for i, f in enumerate(files):
        fn = f.get("filename") or ("doc%d.txt" % i)
        text = f.get("text") or ""
        b64 = f.get("file_b64") or ""
        if b64 and not text:
            try:
                raw = base64.b64decode(b64.split(",")[-1])
                text = _docx_text(raw) if fn.lower().endswith(".docx") else raw.decode("utf-8", "replace")
            except Exception:
                text = ""
        if len(text.strip()) < 10:
            continue
        base_fn = "".join(ch if ch.isalnum() or ch in " ._-" else "_" for ch in os.path.splitext(fn)[0])[:50]
        open(os.path.join(folder, base_fn + ".txt"), "w", encoding="utf-8").write(text)
        saved += 1
    if saved == 0:
        return {"status": "error", "message": "не удалось прочитать документы"}
    r = run_expert("kp_ingest", {"name": name, "folder": folder}, 300)
    if not isinstance(r, dict) or r.get("status") != "success":
        return {"status": "error", "message": "не удалось создать базу: " + str(r)[:200]}
    c = cfg(); kbs = c.get("knowledge_bases") or []
    kbs = [k for k in kbs if (k.get("name") if isinstance(k, dict) else k) != name]
    kbs.append({"name": name, "files": r.get("files", saved), "chunks": r.get("chunks", 0)})
    cfg_save({"knowledge_bases": kbs})
    return {"status": "success", "knowledge_bases": kbs, "detail": r}


def h_kb_remove(body):
    name = (body.get("name") or "").strip()
    c = cfg(); kbs = [k for k in (c.get("knowledge_bases") or []) if (k.get("name") if isinstance(k, dict) else k) != name]
    cfg_save({"knowledge_bases": kbs})
    return {"status": "success", "knowledge_bases": kbs}


def h_reveal(body):
    # открыть папку с готовыми документами в Finder (надёжно во встроенном браузере Extella)
    name = os.path.basename(body.get("name") or "")
    target = os.path.join(OUT_DIR, name) if name and os.path.exists(os.path.join(OUT_DIR, name)) else OUT_DIR
    try:
        if os.path.isdir(target):
            subprocess.Popen(["open", target])
        else:
            subprocess.Popen(["open", "-R", target])
        return {"status": "success", "path": target}
    except Exception as e:
        return {"status": "error", "message": str(e)[:150], "path": OUT_DIR}


ROUTES = {"/x/status": h_status, "/x/save_config": h_save_config, "/x/save_telegram": h_save_telegram,
          "/x/run_review": h_run_review, "/x/negotiate": h_negotiate, "/x/notify": h_notify,
          "/x/assist": h_assist, "/x/save_email": h_save_email, "/x/save_whatsapp": h_save_whatsapp,
          "/x/upload_policy": h_upload_policy, "/x/clear_policies": h_clear_policies,
          "/x/clients": h_clients, "/x/add_client": h_add_client, "/x/upload_clients": h_upload_clients,
          "/x/send_email": h_send_email, "/x/send_wa": h_send_wa, "/x/reveal": h_reveal,
          "/x/review_progress": h_review_progress,
          "/x/kb_status": h_kb_status, "/x/kb_add_legal": h_kb_add_legal, "/x/kb_remove_legal": h_kb_remove_legal,
          "/x/kb_create": h_kb_create, "/x/kb_remove": h_kb_remove}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, (bytes, bytearray)) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = unquote(self.path.split("?")[0])
        if path in ("/", "/onboarding.html", "/index.html"):
            f = os.path.join(HERE, "onboarding.html")
            if os.path.exists(f):
                self._send(200, open(f, "rb").read(), "text/html; charset=utf-8")
            else:
                self._send(404, {"error": "onboarding.html not found"})
            return
        if path.startswith("/out/"):
            name = os.path.basename(path[len("/out/"):])
            fp = os.path.join(OUT_DIR, name)
            if os.path.exists(fp):
                ctype = mimetypes.guess_type(fp)[0] or "application/octet-stream"
                with open(fp, "rb") as fh:
                    data = fh.read()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                # RFC 5987: имя файла может быть кириллическим; заголовки — latin-1, поэтому кодируем
                disp = "attachment; filename=\"document%s\"; filename*=UTF-8''%s" % (
                    os.path.splitext(name)[1], quote(name))
                self.send_header("Content-Disposition", disp)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers(); self.wfile.write(data)
            else:
                self._send(404, {"error": "not found"})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        ln = int(self.headers.get("Content-Length", 0) or 0)
        try:
            body = json.loads(self.rfile.read(ln).decode("utf-8")) if ln else {}
        except Exception:
            body = {}
        fn = ROUTES.get(path)
        if not fn:
            self._send(404, {"error": "unknown route"}); return
        try:
            self._send(200, fn(body))
        except Exception as e:
            self._send(200, {"status": "error", "message": str(e)[:300]})


if __name__ == "__main__":
    print("Extella Contract Agent bridge on http://127.0.0.1:%d/" % PORT)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
