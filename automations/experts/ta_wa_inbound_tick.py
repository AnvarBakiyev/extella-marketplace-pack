# expert: ta_wa_inbound_tick
# description: Travel Agency pack: drain GreenAPI incoming-message queue and run a conversational lead-qualifier in WhatsApp (5 slots -> Tourvisor offer). Autopilot only qualifies + sends the first offer; any client reply after the offer is handed to a human manager (client rule). Gated by KV ta:inbound:enabled. Params: max_msgs, simulate_from, simulate_text, dry_run (test without touching GreenAPI), api_token.

def ta_wa_inbound_tick(max_msgs=10, simulate_from="", simulate_text="", start_phone="", start_name="", dry_run=0, api_token="") -> str:
    import json, os, ssl, ast, time, urllib.request, urllib.parse

    try:
        cfg = json.load(open(os.path.join(os.environ.get("EXTELLA_WIZARD_ROOT") or os.path.expanduser("~/extella_wizard"), "app", "config.json"), encoding="utf-8"))
    except Exception:
        cfg = {}
    tok = api_token if api_token and not str(api_token).startswith("{{") else cfg.get("auth_token", "")
    if not tok:
        return json.dumps({"status": "error", "error": "no_api_token"}, ensure_ascii=False)
    dry = str(dry_run) in ("1", "true", "True", True)
    agent = cfg.get("agent_id", "__EXTELLA_AGENT__") or "__EXTELLA_AGENT__"
    qwen = "__EXTELLA_AGENT__"
    iid = cfg.get("greenapi_id", ""); gtok = cfg.get("greenapi_token", "")

    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    HDR = {"X-Auth-Token": tok, "Content-Type": "application/json", "X-Profile-Id": "default",
           "X-Agent-Id": cfg.get("agent_id", "__EXTELLA_AGENT__")}

    def xapi(path, payload, timeout=120):
        req = urllib.request.Request("https://api.extella.ai" + path, data=json.dumps(payload).encode("utf-8"),
                                     headers=HDR, method="POST")
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return json.loads(r.read().decode("utf-8"))

    def kv_get(key):
        try:
            return (xapi("/api/kv/get", {"key": key, "global": True}, 30) or {}).get("value") or ""
        except Exception:
            return ""

    def kv_set(key, value, desc=""):
        try:
            xapi("/api/kv/set", {"key": key, "value": value, "description": desc, "global": True}, 30)
        except Exception:
            pass

    enabled = (kv_get("ta:inbound:enabled") or "0").strip() in ("1", "true", "on", "yes")
    is_start = bool(start_phone)
    is_sim = bool(simulate_from and simulate_text)
    if not enabled and not is_sim and not is_start:
        return json.dumps({"status": "success", "enabled": False, "processed": 0,
                           "note": "Автоответчик выключен (KV ta:inbound:enabled)"}, ensure_ascii=False)

    try:
        ta_conf = json.loads(kv_get("ta:config") or "{}")
    except Exception:
        ta_conf = {}
    dep_default = ta_conf.get("departure_id", 0)
    cur_default = ta_conf.get("currency", "KZT")

    # База клиентов для узнавания входящего (приветствие по имени + история)
    base_by_phone = {}
    try:
        for c in json.loads(kv_get("ta:clients") or "[]"):
            d = "".join(ch for ch in str(c.get("phone", "")) if ch.isdigit())
            if d:
                base_by_phone[d] = c
    except Exception:
        base_by_phone = {}

    def client_ctx(phone_digits):
        c = base_by_phone.get(phone_digits)
        if not c:
            return "", ""
        trips = c.get("trips") or []
        tx = "; ".join("%s (%s)" % (t.get("destination", "?"), t.get("date", "?")) for t in trips[-3:])
        return c.get("name", ""), tx

    # Разрешённые номера: клиенты из базы + те, кому агентство написало первым (ta:inbound:allow)
    try:
        allow_set = set(json.loads(kv_get("ta:inbound:allow") or "[]"))
    except Exception:
        allow_set = set()
    # режим: "clients" (по умолчанию — только база+allow) или "all" (любой входящий)
    inbound_mode = (kv_get("ta:inbound:mode") or "clients").strip().lower()

    def is_allowed(phone_digits, state):
        if inbound_mode == "all":
            return True
        return (phone_digits in base_by_phone) or bool(state.get("initiated")) or (phone_digits in allow_set)

    def allow_add(phone_digits):
        if phone_digits and phone_digits not in allow_set:
            allow_set.add(phone_digits)
            kv_set("ta:inbound:allow", json.dumps(sorted(allow_set)), "TA inbound allowlist (agency-initiated + approved)")

    def gapi_get(method, params=None, timeout=30):
        qs = ("?" + urllib.parse.urlencode(params)) if params else ""
        url = "https://api.green-api.com/waInstance%s/%s/%s%s" % (iid, method, gtok, qs)
        with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout, context=ctx) as r:
            body = r.read().decode("utf-8", errors="replace")
            return json.loads(body) if body.strip() else None

    def gapi_delete(receipt_id):
        url = "https://api.green-api.com/waInstance%s/deleteNotification/%s/%s" % (iid, gtok, receipt_id)
        req = urllib.request.Request(url, method="DELETE")
        try:
            urllib.request.urlopen(req, timeout=20, context=ctx).read()
        except Exception:
            pass

    def wa_send(phone_digits, text):
        if dry:
            return {"dry_run": True}
        url = "https://api.green-api.com/waInstance%s/sendMessage/%s" % (iid, gtok)
        body = json.dumps({"chatId": phone_digits + "@c.us", "message": text}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=25, context=ctx) as r:
                return json.loads(r.read().decode("utf-8", errors="replace"))
        except Exception as e:
            return {"error": str(e)[:150]}

    def call_expert(name, params, timeout=300):
        out = xapi("/api/expert/run", {"expert_name": name, "params": params, "global": True}, timeout)
        if isinstance(out, dict) and out.get("task_id") and "deferred" in str(out.get("result", "")).lower():
            tid = out["task_id"]; waited = 0
            while waited < timeout:
                time.sleep(4); waited += 4
                try:
                    stt = xapi("/api/tasks/check", {"task_id": tid}, 30)
                except Exception:
                    continue
                if str(stt.get("status", "")).lower() in ("completed", "success", "done", "error", "failed"):
                    out = stt; break
        res = out.get("result", out) if isinstance(out, dict) else out
        for _ in range(3):
            if isinstance(res, dict) and isinstance(res.get("result"), str):
                res = res["result"]
            if isinstance(res, str):
                try:
                    res = json.loads(res)
                except Exception:
                    try:
                        res = ast.literal_eval(res)
                    except Exception:
                        return {"status": "error", "raw": str(res)[:300]}
        return res if isinstance(res, dict) else {"status": "error", "raw": str(res)[:300]}

    def _scrub(t):
        for marker in ("\U0001F50D Ты только что", "\U0001F4A1 Чтобы отключить", "отключи обучение"):
            i = t.find(marker)
            if i > 20:
                t = t[:i]
        return t.strip()

    def qwen_step(state, user_msg, ctx_name="", ctx_trips=""):
        """Возвращает (updated_slots, ready, reply_text)."""
        slots = state.get("slots", {})
        today = time.strftime("%Y-%m-%d")
        known = ", ".join("%s=%s" % (k, v) for k, v in slots.items() if v) or "ничего"
        ctx_line = ""
        if ctx_name:
            ctx_line = "Это НАШ постоянный клиент, зовут %s." % ctx_name
            if ctx_trips:
                ctx_line += " Прошлые поездки с нами: %s. Можешь тепло поприветствовать по имени и опереться на историю." % ctx_trips
            ctx_line += "\n"
        prompt = (
            "Ты — вежливый ассистент турагентства, общаешься с клиентом в WhatsApp по-русски. "
            "Задача: собрать 5 параметров для подбора тура, задавая ПО ОДНОМУ вопросу за раз, дружелюбно и коротко.\n"
            "Параметры: direction (страна), date_from и date_to (даты вылета, формат ГГГГ-ММ-ДД, диапазон не более 14 дней), "
            "adults (взрослых), children (возраст детей через запятую или пусто), budget (бюджет в тенге, число).\n"
            "Сегодня: %s. Город вылета по умолчанию уже известен, про него НЕ спрашивай.\n"
            "%s"
            "Уже собрано: %s\n"
            "Новое сообщение клиента: \"%s\"\n\n"
            "Извлеки то, что клиент сообщил (в т.ч. если он ответил на несколько вопросов сразу). "
            "Если чего-то не хватает — задай следующий недостающий вопрос. Если всё собрано — напиши короткую реплику "
            "«Спасибо! Подбираю для вас варианты, пришлю через минуту 🙌».\n"
            "Ответь СТРОГО в формате (каждое поле с новой строки, неизвестные пропусти):\n"
            "DIRECTION: <страна или ->\n"
            "DATE_FROM: <ГГГГ-ММ-ДД или ->\n"
            "DATE_TO: <ГГГГ-ММ-ДД или ->\n"
            "ADULTS: <число или ->\n"
            "CHILDREN: <возрасты через запятую или ->\n"
            "BUDGET: <число или ->\n"
            "READY: <yes или no>\n"
            "REPLY: <твоё сообщение клиенту>"
        ) % (today, ctx_line, known, user_msg[:500])
        try:
            out = xapi("/api/agent/run", {"agent_id": qwen, "input": prompt, "store": False,
                                          "tool_choice": "none", "temperature": 0.3, "max_output_tokens": 450}, 120)
            txt = ""
            for item in (out.get("output") or []):
                if item.get("type") == "message":
                    for c in (item.get("content") or []):
                        if c.get("text"):
                            txt = c["text"]
            txt = _scrub(txt)
        except Exception as e:
            return slots, False, "Извините, отвечу чуть позже — уже смотрю ваш запрос."

        new = dict(slots); ready = False; reply = ""
        lines = txt.splitlines()
        for i, ln in enumerate(lines):
            up = ln.strip()
            if up.upper().startswith("REPLY:"):
                reply = up[6:].strip()
                if i + 1 < len(lines):
                    reply = (reply + "\n" + "\n".join(lines[i + 1:])).strip()
                break
            for field, key in (("DIRECTION", "direction"), ("DATE_FROM", "date_from"), ("DATE_TO", "date_to"),
                               ("ADULTS", "adults"), ("CHILDREN", "children"), ("BUDGET", "budget")):
                if up.upper().startswith(field + ":"):
                    val = up.split(":", 1)[1].strip()
                    if val and val not in ("-", "—", "unknown", "не указано"):
                        new[key] = val
            if up.upper().startswith("READY:"):
                ready = up.split(":", 1)[1].strip().lower().startswith("y")
        need = ("direction", "date_from", "date_to", "adults", "budget")
        ready = ready and all(new.get(k) for k in need)
        if not reply:
            reply = "Подскажите, пожалуйста, куда хотели бы поехать?"
        return new, ready, reply

    def handle_message(phone_digits, name, text, force_allow=False):
        state = {}
        try:
            state = json.loads(kv_get("ta:conv:" + phone_digits) or "{}")
        except Exception:
            state = {}
        stage = state.get("stage", "new")
        # Фильтр: бот отвечает ТОЛЬКО клиентам из базы / кому агентство написало первым
        if not force_allow and not is_allowed(phone_digits, state):
            return {"phone": "+" + phone_digits, "action": "ignored", "reason": "не в базе клиентов"}
        state.setdefault("phone", "+" + phone_digits)
        base_name, base_trips = client_ctx(phone_digits)
        if name:
            state["name"] = name
        elif base_name and not state.get("name"):
            state["name"] = base_name

        # Клиент вернулся после отправленного предложения -> живой менеджер (правило клиента)
        if stage in ("offered", "handed_over"):
            if stage != "handed_over":
                state["stage"] = "handed_over"; state["updated_at"] = time.strftime("%Y-%m-%d %H:%M")
                kv_set("ta:conv:" + phone_digits, json.dumps(state, ensure_ascii=False), "TA conversation (handed to manager)")
                if not dry:
                    call_expert("ta_lead_upsert", {"phone": "+" + phone_digits, "status": "handed_over",
                                                   "note": "клиент ответил на предложение — передан менеджеру",
                                                   "api_token": tok}, 60)
                    if cfg.get("telegram_bot_token") and cfg.get("telegram_chat_id"):
                        try:
                            body = json.dumps({"chat_id": cfg["telegram_chat_id"],
                                               "text": "📞 Travel Agency: клиент %s (%s) ответил на предложение — нужен менеджер. Текст: «%s»" % (state.get("name", ""), "+" + phone_digits, text[:200])}).encode("utf-8")
                            urllib.request.urlopen(urllib.request.Request("https://api.telegram.org/bot%s/sendMessage" % cfg["telegram_bot_token"],
                                                   data=body, headers={"Content-Type": "application/json"}, method="POST"), timeout=15, context=ctx)
                        except Exception:
                            pass
                    wa_send(phone_digits, "Спасибо за ответ! Передаю ваш вопрос личному менеджеру — он свяжется с вами совсем скоро 🙌")
            return {"phone": "+" + phone_digits, "action": "handed_over", "reply": "передан менеджеру"}

        # Квалификация (с узнаванием клиента из базы)
        new_slots, ready, reply = qwen_step(state, text, base_name, base_trips)
        state["slots"] = new_slots
        state["stage"] = "collecting"
        state["updated_at"] = time.strftime("%Y-%m-%d %H:%M")
        hist = state.get("history", []); hist.append({"from": "client", "text": text[:300]}); hist.append({"from": "bot", "text": reply[:300]})
        state["history"] = hist[-12:]

        if ready:
            kv_set("ta:conv:" + phone_digits, json.dumps(state, ensure_ascii=False), "TA conversation (qualifying)")
            if not dry:
                wa_send(phone_digits, reply)  # «Спасибо, подбираю…»
            if dry:
                return {"phone": "+" + phone_digits, "action": "READY", "slots": new_slots, "reply": reply,
                        "note": "dry_run: пайплайн НЕ запускался"}
            childs = [a.strip() for a in str(new_slots.get("children", "")).split(",") if a.strip().isdigit()]
            pipe = call_expert("ta_run_lead_pipeline", {
                "phone": "+" + phone_digits, "fio": state.get("name", ""), "channel": "whatsapp",
                "direction": new_slots.get("direction", ""), "date_from": new_slots.get("date_from", ""),
                "date_to": new_slots.get("date_to", ""), "adults": new_slots.get("adults", 2),
                "childs_json": json.dumps([int(x) for x in childs]), "budget": new_slots.get("budget", 0),
                "currency": cur_default, "departure_id": dep_default}, 420)
            if pipe.get("status") == "success" and pipe.get("message"):
                wa_send(phone_digits, pipe["message"])
                state["stage"] = "offered"
                kv_set("ta:conv:" + phone_digits, json.dumps(state, ensure_ascii=False), "TA conversation (offer sent)")
                return {"phone": "+" + phone_digits, "action": "offer_sent", "options": pipe.get("picks_total")}
            else:
                wa_send(phone_digits, "Спасибо! По вашему запросу подберу варианты и вернусь чуть позже.")
                state["stage"] = "offered"  # чтобы дальше ушло менеджеру
                kv_set("ta:conv:" + phone_digits, json.dumps(state, ensure_ascii=False), "TA conversation (offer pending)")
                return {"phone": "+" + phone_digits, "action": "offer_failed", "detail": pipe.get("error", "")}
        else:
            kv_set("ta:conv:" + phone_digits, json.dumps(state, ensure_ascii=False), "TA conversation (qualifying)")
            if not dry:
                wa_send(phone_digits, reply)
            return {"phone": "+" + phone_digits, "action": "ask", "reply": reply, "slots": new_slots}

    processed = []

    # Режим симуляции: один искусственный входящий (тест логики без GreenAPI)
    if simulate_from and simulate_text:
        digits = "".join(c for c in str(simulate_from) if c.isdigit())
        processed.append(handle_message(digits, "", str(simulate_text), force_allow=True))
        return json.dumps({"status": "success", "mode": "simulate", "dry_run": dry, "processed": processed}, ensure_ascii=False)

    # Режим «написать лиду первым»: агентство инициирует диалог (лид пришёл от лидогенератора)
    if is_start:
        digits = "".join(c for c in str(start_phone) if c.isdigit())
        if not digits:
            return json.dumps({"status": "error", "error": "start_phone required"}, ensure_ascii=False)
        base_name, base_trips = client_ctx(digits)
        nm = (start_name if start_name and not str(start_name).startswith("{{") else "") or base_name
        greet = "%s, здравствуйте! 👋 Это турагентство%s. Помогу подобрать для вас тур — расскажите, куда хотели бы поехать?" % (
            nm or "Здравствуйте", (" «%s»" % ta_conf.get("agency_name")) if ta_conf.get("agency_name") else "")
        if not nm:
            greet = "Здравствуйте! 👋 Это турагентство%s. Помогу подобрать для вас тур — расскажите, куда хотели бы поехать?" % (
                (" «%s»" % ta_conf.get("agency_name")) if ta_conf.get("agency_name") else "")
        state = {"phone": "+" + digits, "name": nm, "stage": "collecting", "slots": {},
                 "history": [{"from": "bot", "text": greet}], "updated_at": time.strftime("%Y-%m-%d %H:%M"),
                 "initiated": True}
        allow_add(digits)  # разрешаем ответы от этого лида (агентство написало первым)
        kv_set("ta:conv:" + digits, json.dumps(state, ensure_ascii=False), "TA conversation (agency-initiated)")
        if not dry and iid and gtok:
            wa_send(digits, greet)
        call_expert("ta_lead_upsert", {"phone": "+" + digits, "fio": nm, "channel": "whatsapp",
                                       "status": "qualified", "note": "бот начал переписку", "api_token": tok}, 60)
        return json.dumps({"status": "success", "mode": "start", "phone": "+" + digits, "greeting": greet,
                           "recognized": bool(base_name)}, ensure_ascii=False)

    if not iid or not gtok:
        return json.dumps({"status": "error", "error": "no_greenapi_credentials"}, ensure_ascii=False)

    # Дренаж очереди входящих
    try:
        limit = max(1, min(int(max_msgs), 30))
    except Exception:
        limit = 10
    drained = 0
    for _ in range(limit):
        try:
            note = gapi_get("receiveNotification", {"receiveTimeout": 5}, 25)
        except Exception as e:
            processed.append({"error": "receive: " + str(e)[:120]}); break
        if not note or not note.get("receiptId"):
            break
        receipt = note["receiptId"]; body = note.get("body", {}) or {}
        try:
            if body.get("typeWebhook") == "incomingMessageReceived":
                md = body.get("messageData", {}) or {}
                tm = md.get("typeMessage", "")
                text = ""
                if tm == "textMessage":
                    text = (md.get("textMessageData", {}) or {}).get("textMessage", "")
                elif tm == "extendedTextMessage":
                    text = (md.get("extendedTextMessageData", {}) or {}).get("text", "")
                sd = body.get("senderData", {}) or {}
                chat = sd.get("chatId", "")
                if text and chat.endswith("@c.us"):
                    digits = chat.split("@")[0]
                    processed.append(handle_message(digits, sd.get("senderName", ""), text))
                    drained += 1
        except Exception as e:
            processed.append({"error": "handle: " + str(e)[:150]})
        finally:
            gapi_delete(receipt)

    return json.dumps({"status": "success", "enabled": True, "processed": len(processed),
                       "handled": drained, "details": processed}, ensure_ascii=False)