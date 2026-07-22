#!/usr/bin/env python3
"""Travel Agency pack — onboarding bridge (localhost:8766).

Маршруты: / и /onboarding.html — страница онбординга; /x/* — JSON API.
Секреты живут в защищённом platform-native конфиге Extella Client.
Сервер локальный (127.0.0.1), наружу ничего не открывает."""
import json, os, ssl, time, csv, io, base64, re, tempfile, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from extella_expert_bridge import account_config, locations, path_or_error

PORT = 8766
HERE = os.path.dirname(os.path.abspath(__file__))
LOCATIONS = locations()
CFG_PATH = LOCATIONS["account_config"]
CTX = ssl.create_default_context()


def cfg():
    return account_config()


def cfg_save(patch):
    c = cfg(); c.update(patch)
    os.makedirs(os.path.dirname(CFG_PATH), exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".config.", dir=os.path.dirname(CFG_PATH))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(c, handle, ensure_ascii=False)
            handle.flush(); os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, CFG_PATH)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    return c


def xapi(path, payload, timeout=120):
    c = cfg()
    agent_id = str(c.get("agent_id") or "")
    if not re.fullmatch(r"agent_[A-Za-z0-9_-]{6,128}", agent_id):
        raise RuntimeError("Current-account Extella agent is not configured")
    api_base = str(c.get("api_base") or "https://api.extella.ai").rstrip("/")
    req = urllib.request.Request(api_base + path, data=json.dumps(payload).encode("utf-8"),
                                 headers={"X-Auth-Token": c.get("auth_token", ""), "Content-Type": "application/json",
                                          "X-Profile-Id": "default",
                                          "X-Agent-Id": agent_id}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return json.loads(r.read().decode("utf-8"))


def run_expert(name, params, timeout=300):
    """Run expert with deferred-task polling; returns parsed dict."""
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
        else:
            return {"status": "error", "error": "task timeout", "task_id": tid}
    res = out.get("result", out) if isinstance(out, dict) else out
    for _ in range(3):
        if isinstance(res, dict) and isinstance(res.get("result"), str):
            res = res["result"]
        if isinstance(res, str):
            try:
                res = json.loads(res)
            except Exception:
                try:
                    import ast
                    res = ast.literal_eval(res)
                except Exception:
                    return {"status": "error", "error": "unparsable", "raw": str(res)[:400]}
    return res if isinstance(res, dict) else {"status": "error", "raw": str(res)[:400]}


def kv_get(key):
    try:
        return (xapi("/api/kv/get", {"key": key, "global": True}, 30) or {}).get("value") or ""
    except Exception:
        return ""


def kv_set(key, value, desc=""):
    return xapi("/api/kv/set", {"key": key, "value": value, "description": desc, "global": True}, 30)


# ---------- handlers ----------

def h_status(_):
    c = cfg()
    tv = {"connected": bool(c.get("tourvisor_jwt"))}
    if tv["connected"]:
        r = run_expert("ta_tv_get", {"path": "/departures"}, 60)
        tv["ok"] = r.get("status") == "success" and r.get("status_code") == 200
        tv["departures"] = [{"id": d.get("id"), "name": d.get("name")} for d in (r.get("data") or [])][:30] if tv["ok"] else []
        if not tv["ok"]:
            tv["error"] = r.get("error", "")
    wa = {"connected": bool(c.get("greenapi_id") and c.get("greenapi_token"))}
    if wa["connected"]:
        r = run_expert("ta_wa_state", {}, 60)
        wa["authorized"] = bool(r.get("authorized"))
        wa["state"] = r.get("state", r.get("error", ""))
    try:
        clients = json.loads(kv_get("ta:clients") or "[]")
    except Exception:
        clients = []
    try:
        ta_conf = json.loads(kv_get("ta:config") or "{}")
    except Exception:
        ta_conf = {}
    try:
        leads = json.loads(kv_get("ta:leads:index") or "[]")
    except Exception:
        leads = []
    tg = {"connected": bool(c.get("telegram_bot_token") and c.get("telegram_chat_id"))}
    inbound = (kv_get("ta:inbound:enabled") or "0").strip() in ("1", "true", "on", "yes")
    return {"status": "success", "tourvisor": tv, "whatsapp": wa, "telegram": tg, "inbound": inbound,
            "clients_count": len(clients), "config": ta_conf, "leads": leads}


def h_save_tourvisor(body):
    jwt = (body.get("jwt") or "").strip()
    if not jwt.startswith("eyJ"):
        return {"status": "error", "error": "это не похоже на JWT-токен"}
    cfg_save({"tourvisor_jwt": jwt})
    r = run_expert("ta_tv_get", {"path": "/departures"}, 60)
    ok = r.get("status") == "success" and r.get("status_code") == 200
    return {"status": "success" if ok else "error",
            "checked": ok, "error": "" if ok else r.get("error", "токен не прошёл проверку"),
            "departures": [{"id": d.get("id"), "name": d.get("name")} for d in (r.get("data") or [])][:30]}


def h_save_greenapi(body):
    iid = (body.get("id") or "").strip(); tok = (body.get("token") or "").strip()
    if not iid or not tok:
        return {"status": "error", "error": "нужны idInstance и apiTokenInstance"}
    cfg_save({"greenapi_id": iid, "greenapi_token": tok})
    r = run_expert("ta_wa_state", {}, 60)
    return {"status": "success" if r.get("status") == "success" else "error",
            "state": r.get("state", ""), "authorized": bool(r.get("authorized")), "error": r.get("error", "")}


def h_save_config(body):
    try:
        cur = json.loads(kv_get("ta:config") or "{}")
    except Exception:
        cur = {}
    for k in ("departure_id", "agency_name", "manager_name", "currency", "band_pct"):
        if body.get(k) not in (None, ""):
            cur[k] = body[k]
    try:
        cur["departure_id"] = int(cur.get("departure_id") or 0)
    except Exception:
        pass
    kv_set("ta:config", json.dumps(cur, ensure_ascii=False), "Travel Agency pack config")
    return {"status": "success", "config": cur}


def h_upload_clients(body):
    """CSV: name,phone,birthday,last_destination,last_date,last_budget (первая строка может быть заголовком)."""
    text = body.get("csv") or ""
    if not text.strip():
        return {"status": "error", "error": "пустой CSV"}
    rows = list(csv.reader(io.StringIO(text)))
    clients = []
    for row in rows:
        if len(row) < 2 or not row[1].strip() or "phone" in row[1].lower() or "телефон" in row[1].lower():
            continue
        c = {"name": row[0].strip(), "phone": row[1].strip(),
             "birthday": row[2].strip() if len(row) > 2 else "", "currency": "KZT", "trips": []}
        if len(row) > 3 and row[3].strip():
            trip = {"destination": row[3].strip(), "date": row[4].strip() if len(row) > 4 else ""}
            if len(row) > 5:
                try:
                    trip["budget"] = int(float(row[5].replace(" ", "")))
                except Exception:
                    pass
            c["trips"].append(trip)
        clients.append(c)
    if not clients:
        return {"status": "error", "error": "не разобрал ни одной строки (формат: имя,телефон,ДР,направление,дата,бюджет)"}
    kv_set("ta:clients", json.dumps(clients, ensure_ascii=False), "TA client base (uploaded via onboarding)")
    return {"status": "success", "count": len(clients), "sample": clients[:3]}


def h_run_lead(body):
    params = {"phone": body.get("phone", ""), "fio": body.get("fio", ""), "channel": body.get("channel", "whatsapp"),
              "direction": body.get("direction", ""), "date_from": body.get("date_from", ""),
              "date_to": body.get("date_to", ""), "nights_from": body.get("nights_from", 7),
              "nights_to": body.get("nights_to", 10), "adults": body.get("adults", 2),
              "childs_json": body.get("childs_json", "[]"), "budget": body.get("budget", 0),
              "currency": body.get("currency", "")}
    return run_expert("ta_run_lead_pipeline", params, 420)


def h_drafts(_):
    """Собирает черновики: по лидам + сегодняшние кампании по базе."""
    items = []
    try:
        leads = json.loads(kv_get("ta:leads:index") or "[]")
    except Exception:
        leads = []
    for ph in leads[-50:]:
        v = kv_get("ta:draft:" + ph)
        if v:
            try:
                d = json.loads(v); d["_key"] = "ta:draft:" + ph; items.append(d)
            except Exception:
                pass
    stamp = time.strftime("%Y%m%d")
    try:
        clients = json.loads(kv_get("ta:clients") or "[]")
    except Exception:
        clients = []
    for c in clients:
        ph = "".join(x for x in str(c.get("phone", "")) if x.isdigit() or x == "+")
        for kind in ("bday", "season"):
            k = "ta:draft:%s:%s:%s" % (kind, stamp, ph)
            v = kv_get(k)
            if v:
                try:
                    d = json.loads(v); d["_key"] = k; items.append(d)
                except Exception:
                    pass
    items.sort(key=lambda d: d.get("created_at", ""), reverse=True)
    return {"status": "success", "drafts": items}


def h_send(body):
    key = body.get("draft_key", "")
    if not key:
        return {"status": "error", "error": "draft_key required"}
    return run_expert("ta_wa_send", {"draft_key": key}, 90)


def h_run_birthday(body):
    return run_expert("ta_birthday_scan", {"days_ahead": body.get("days_ahead", 0),
                                           "phones_json": json.dumps(body.get("phones") or [])}, 300)


def h_run_season(body):
    return run_expert("ta_season_campaign", {"season": body.get("season", "лето"), "max_clients": body.get("max_clients", 20),
                                             "phones_json": json.dumps(body.get("phones") or [])}, 420)



def h_save_telegram(body):
    tok = (body.get("bot_token") or "").strip(); cid = (body.get("chat_id") or "").strip()
    if not tok or not cid:
        return {"status": "error", "error": "нужны bot_token и chat_id"}
    cfg_save({"telegram_bot_token": tok, "telegram_chat_id": cid})
    r = run_expert("ta_tg_send", {"text": "✅ Travel Agency: Telegram-уведомления подключены. Сюда будут приходить сигналы о готовых черновиках."}, 60)
    return {"status": r.get("status", "error"), "error": r.get("error", "")}



def local_ocr(path):
    """OCR на этом устройстве (у моста есть tesseract) — не зависим от того, куда платформа роутит эксперт."""
    import subprocess
    tess, state = path_or_error("tesseract", repair=True)
    if not tess:
        return "__OCR_ERR__" + str(state.get("message") or "tesseract unavailable")[:120]
    try:
        out = subprocess.run([tess, path, "stdout", "--psm", "6"], capture_output=True, text=True, timeout=60)
        return out.stdout or ""
    except Exception as e:
        return "__OCR_ERR__" + str(e)[:120]


def h_passport_demo(body):
    img = body.get("image_path") or os.path.join(HERE, "passport_specimen.png")
    if not os.path.exists(img):
        return {"status": "error", "error": "файл образца не найден: " + img}
    txt = local_ocr(img)
    if txt.startswith("__OCR_ERR__"):
        return {"status": "error", "error": "OCR не запустился: " + txt[11:], "hint": "проверьте установку tesseract"}
    return run_expert("ta_passport_extract", {"mrz_text": txt}, 120)


def h_contract(body):
    return run_expert("ta_contract_generate", {"doc_no": body.get("doc_no", ""),
                                               "draft_phone": body.get("draft_phone", "")}, 120)



def h_clients(_):
    """Список клиентов базы (для выбора в Продажах и Маркетинге)."""
    try:
        clients = json.loads(kv_get("ta:clients") or "[]")
    except Exception:
        clients = []
    out = []
    for c in clients:
        trips = c.get("trips") or []
        last = trips[-1] if trips else {}
        budgets = [t.get("budget") for t in trips if t.get("budget")]
        out.append({"name": c.get("name"), "phone": c.get("phone"), "birthday": c.get("birthday", ""),
                    "last_destination": last.get("destination", ""), "last_date": last.get("date", ""),
                    "avg_budget": int(sum(budgets) / len(budgets)) if budgets else 0})
    return {"status": "success", "clients": out}


def h_leads(_):
    """Список лидов со статусами и черновиками (видимая воронка Продаж)."""
    items = []
    try:
        idx = json.loads(kv_get("ta:leads:index") or "[]")
    except Exception:
        idx = []
    for ph in idx[-100:]:
        lead = {}
        try:
            lead = json.loads(kv_get("ta:lead:" + ph) or "{}")
        except Exception:
            lead = {"phone": ph}
        d = {}
        try:
            d = json.loads(kv_get("ta:draft:" + ph) or "{}")
        except Exception:
            d = {}
        items.append({"phone": ph, "fio": lead.get("fio", ""), "channel": lead.get("channel", ""),
                      "status": d.get("status") if d.get("status") == "sent" else lead.get("status", "new"),
                      "answers": lead.get("answers", {}), "updated_at": lead.get("updated_at", ""),
                      "draft": ({"message": d.get("message", ""), "status": d.get("status", ""),
                                 "created_at": d.get("created_at", ""), "_key": "ta:draft:" + ph} if d.get("message") else None)})
    items.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return {"status": "success", "leads": items}


def h_upload_passport(body):
    """Скан паспорта из панели: base64 -> файл -> ta_passport_extract."""
    b64 = body.get("image_b64") or ""
    if not b64:
        return {"status": "error", "error": "нет файла"}
    if "," in b64[:80]:
        b64 = b64.split(",", 1)[1]
    try:
        raw = base64.b64decode(b64)
    except Exception:
        return {"status": "error", "error": "не удалось декодировать файл"}
    if len(raw) > 15 * 1024 * 1024:
        return {"status": "error", "error": "файл больше 15 МБ"}
    up_dir = os.path.join(HERE, "uploads")
    os.makedirs(up_dir, exist_ok=True)
    ext = "pdf" if raw[:5] == b"%PDF-" else "png"
    path = os.path.join(up_dir, "passport_%s.%s" % (time.strftime("%Y%m%d_%H%M%S"), ext))
    open(path, "wb").write(raw)
    txt = local_ocr(path)
    try:
        os.remove(path)  # ПДн: скан не храним, данные ушли в карточку
    except Exception:
        pass
    if txt.startswith("__OCR_ERR__"):
        return {"status": "error", "error": "OCR не запустился: " + txt[11:]}
    return run_expert("ta_passport_extract", {"mrz_text": txt}, 180)


def h_send_bulk(body):
    """Отправка выбранных черновиков (галочки в панели)."""
    keys = body.get("draft_keys") or []
    if not isinstance(keys, list) or not keys:
        return {"status": "error", "error": "ничего не выбрано"}
    results = []
    for k in keys[:50]:
        r = run_expert("ta_wa_send", {"draft_key": k}, 90)
        results.append({"key": k, "status": r.get("status"), "error": r.get("error", "")})
        time.sleep(1.2)  # мягкая пауза между отправками — не спамим
    ok = sum(1 for r in results if r["status"] == "success")
    return {"status": "success", "sent": ok, "total": len(results), "results": results}



def h_inbound_status(_):
    return {"status": "success",
            "enabled": (kv_get("ta:inbound:enabled") or "0").strip() in ("1", "true", "on", "yes")}


def greenapi_set_incoming(yes=True):
    """Включает/выключает приём входящих уведомлений в GreenAPI (нужно, чтобы бот видел сообщения)."""
    c = cfg(); iid = c.get("greenapi_id"); gtok = c.get("greenapi_token")
    if not iid or not gtok:
        return {"ok": False, "error": "no_greenapi"}
    url = "https://api.green-api.com/waInstance%s/setSettings/%s" % (iid, gtok)
    body = json.dumps({"incomingWebhook": "yes" if yes else "no",
                       "outgoingMessageWebhook": "no", "outgoingAPIMessageWebhook": "no"}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=25, context=CTX) as r:
            return {"ok": True, "resp": json.loads(r.read().decode())}
    except Exception as e:
        return {"ok": False, "error": str(e)[:150]}


def h_inbound_toggle(body):
    on = bool(body.get("enabled"))
    kv_set("ta:inbound:enabled", "1" if on else "0", "TA WhatsApp inbound autopilot toggle")
    wa = {}
    if on:
        wa = greenapi_set_incoming(True)  # чтобы бот начал ВИДЕТЬ входящие
    return {"status": "success", "enabled": on, "greenapi_incoming": wa.get("ok"),
            "note": "GreenAPI: приём входящих включён (инстанс перезагрузится ~1-2 мин)" if on and wa.get("ok") else ""}


def h_inbound_start(body):
    phone = body.get("phone", ""); name = body.get("name", "")
    if not "".join(c for c in str(phone) if c.isdigit()):
        return {"status": "error", "error": "укажите номер лида"}
    return run_expert("ta_wa_inbound_tick", {"start_phone": phone, "start_name": name}, 120)


def h_inbound_test(body):
    phone = body.get("phone") or "+70000000000"
    text = body.get("text") or ""
    if not text.strip():
        return {"status": "error", "error": "введите текст сообщения клиента"}
    r = run_expert("ta_wa_inbound_tick", {"simulate_from": phone, "simulate_text": text, "dry_run": 1}, 240)
    p = (r.get("details") or r.get("processed") or [{}])
    p = p[0] if p else {}
    return {"status": "success", "action": p.get("action"), "reply": p.get("reply", ""),
            "slots": p.get("slots", {}), "note": p.get("note", "")}


def h_inbound_reset(body):
    phone = "".join(c for c in str(body.get("phone") or "") if c.isdigit())
    if phone:
        kv_set("ta:conv:" + phone, "{}", "TA conversation reset")
    return {"status": "success"}


ROUTES = {"/x/status": h_status, "/x/save_tourvisor": h_save_tourvisor, "/x/save_greenapi": h_save_greenapi,
          "/x/save_config": h_save_config, "/x/upload_clients": h_upload_clients, "/x/run_lead": h_run_lead,
          "/x/drafts": h_drafts, "/x/send": h_send, "/x/run_birthday": h_run_birthday, "/x/save_telegram": h_save_telegram, "/x/passport_demo": h_passport_demo, "/x/contract": h_contract, "/x/clients": h_clients, "/x/leads": h_leads, "/x/upload_passport": h_upload_passport, "/x/send_bulk": h_send_bulk, "/x/inbound_status": h_inbound_status, "/x/inbound_toggle": h_inbound_toggle, "/x/inbound_test": h_inbound_test, "/x/inbound_reset": h_inbound_reset, "/x/inbound_start": h_inbound_start, "/x/run_season": h_run_season}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        p = self.path.split("?")[0]
        if p in ("/", "/index.html", "/onboarding.html"):
            try:
                b = open(os.path.join(HERE, "onboarding.html"), "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers(); self.wfile.write(b)
            except Exception as e:
                self._json({"status": "error", "error": str(e)[:200]}, 500)
            return
        if p.startswith("/contracts/"):
            f = os.path.join(HERE, "contracts", os.path.basename(p))
            if os.path.exists(f):
                b = open(f, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers(); self.wfile.write(b)
            else:
                self._json({"status": "error", "error": "contract not found"}, 404)
            return
        if p == "/passport_specimen.png":
            f = os.path.join(HERE, "passport_specimen.png")
            if os.path.exists(f):
                b = open(f, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers(); self.wfile.write(b)
                return
        if p in ROUTES:
            try:
                self._json(ROUTES[p]({}))
            except Exception as e:
                self._json({"status": "error", "error": str(e)[:300]}, 500)
            return
        self._json({"status": "error", "error": "not found"}, 404)

    def do_POST(self):
        p = self.path.split("?")[0]
        if p not in ROUTES:
            self._json({"status": "error", "error": "not found"}, 404); return
        try:
            ln = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(ln).decode("utf-8")) if ln else {}
        except Exception:
            body = {}
        try:
            self._json(ROUTES[p](body))
        except Exception as e:
            self._json({"status": "error", "error": str(e)[:300]}, 500)


def _inbound_poller():
    """Встроенный поллер входящих WhatsApp — делает пак самодостаточным (без внешнего cron/VPS).
    Каждые ~20с, если автоответчик включён и GreenAPI подключён, тянет очередь входящих.
    Гейт по ta:inbound:enabled + фильтр по базе клиентов внутри эксперта."""
    import threading
    def loop():
        while True:
            try:
                time.sleep(20)
                if (kv_get("ta:inbound:enabled") or "0").strip() not in ("1", "true", "on", "yes"):
                    continue
                c = cfg()
                if not (c.get("greenapi_id") and c.get("greenapi_token")):
                    continue
                run_expert("ta_wa_inbound_tick", {"max_msgs": 15}, 200)
            except Exception:
                pass
    t = threading.Thread(target=loop, daemon=True)
    t.start()


if __name__ == "__main__":
    pid_path = os.path.join(HERE, "server.pid")
    try:
        open(pid_path, "w").write(str(os.getpid()))
    except Exception:
        pass
    _inbound_poller()
    print("TA onboarding bridge on http://127.0.0.1:%s/ (+ встроенный поллер входящих)" % PORT)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
