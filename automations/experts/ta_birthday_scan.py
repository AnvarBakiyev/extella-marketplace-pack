# expert: ta_birthday_scan
# description: Travel Agency pack: scan client base (KV ta:clients) for birthdays today or in N days, generate personalized WhatsApp greeting drafts via Qwen agent (tool_choice none), store drafts in KV. Human sends (drafts only). Params: days_ahead (0=today), agent_id (Qwen), api_token.

def ta_birthday_scan(days_ahead=0, phones_json="[]", agent_id="__EXTELLA_AGENT__", api_token="", source_file="", source_key="", target="", client="") -> str:
    import json, os, ssl, time, datetime, urllib.request

    tok = api_token if api_token and not str(api_token).startswith("{{") else ""
    try:
        from extella_expert_bridge import account_config
        cfg = account_config()
    except Exception:
        cfg = {}
    if not tok:
        tok = cfg.get("auth_token", "")
    if not tok:
        return json.dumps({"status": "error", "error": "no_api_token"}, ensure_ascii=False)
    agent = agent_id if agent_id and not str(agent_id).startswith("{{") else "__EXTELLA_AGENT__"

    ctx = ssl.create_default_context()
    HDR = {"X-Auth-Token": tok, "Content-Type": "application/json", "X-Profile-Id": "default",
           "X-Agent-Id": cfg.get("agent_id", "__EXTELLA_AGENT__") if isinstance(cfg, dict) else "__EXTELLA_AGENT__"}

    def api(path, payload, timeout=120):
        req = urllib.request.Request("https://api.extella.ai" + path, data=json.dumps(payload).encode("utf-8"),
                                     headers=HDR, method="POST")
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return json.loads(r.read().decode("utf-8"))

    try:
        got = api("/api/kv/get", {"key": "ta:clients", "global": True}, 30)
        clients = json.loads((got or {}).get("value") or "[]")
    except Exception as e:
        return json.dumps({"status": "error", "error": "cannot read ta:clients: " + str(e)[:150]}, ensure_ascii=False)
    try:
        _phones = json.loads(phones_json) if phones_json and not str(phones_json).startswith("{{") else []
        _phones = {"".join(ch for ch in str(p) if ch.isdigit()) for p in _phones if p}
    except Exception:
        _phones = set()
    if _phones:
        clients = [c for c in clients if "".join(ch for ch in str(c.get("phone", "")) if ch.isdigit()) in _phones]
    if not isinstance(clients, list) or not clients:
        return json.dumps({"status": "success", "found": 0, "note": "ta:clients is empty — upload client base first"}, ensure_ascii=False)

    try:
        ahead = int(days_ahead)
    except Exception:
        ahead = 0
    target = (datetime.date.today() + datetime.timedelta(days=ahead))
    tkey = target.strftime("%m-%d")

    def _scrub(t):
        # cut platform coaching hints the shared Qwen agent may append
        for marker in ("\U0001F50D Ты только что", "\U0001F4A1 Чтобы отключить подсказки", "отключи обучение", "\U0001F50D "):
            i = t.find(marker)
            if i > 20:
                t = t[:i]
        return t.strip().strip('"')

    def agent_text(prompt):
        try:
            out = api("/api/agent/run", {"agent_id": agent, "input": prompt, "store": False,
                                         "tool_choice": "none", "temperature": 0.4, "max_output_tokens": 500}, 120)
            for item in (out.get("output") or []):
                if item.get("type") == "message":
                    for c in (item.get("content") or []):
                        if c.get("text"):
                            return _scrub(c["text"])
        except Exception as e:
            return "__ERR__" + str(e)[:120]
        return ""

    drafts, errors = [], []
    for c in clients:
        bd = str(c.get("birthday", ""))  # expected YYYY-MM-DD or MM-DD
        if not bd:
            continue
        mmdd = bd[5:] if len(bd) >= 8 and bd[4] in "-./" else bd
        mmdd = mmdd.replace(".", "-").replace("/", "-")
        if mmdd != tkey:
            continue
        trips = c.get("trips") or []
        trips_txt = "; ".join("%s, %s" % (t.get("destination", "?"), t.get("date", "?")) for t in trips[-3:]) or "нет данных"
        prompt = ("Ты — ассистент турагентства. Напиши короткое тёплое поздравление с днём рождения для WhatsApp. "
                  "Клиент: %s. Последние путешествия с нами: %s. "
                  "Требования: по-русски, 2-4 предложения, личное упоминание одного из путешествий (если есть), "
                  "без навязчивой рекламы, в конце мягкое приглашение выбрать следующее путешествие. "
                  "Верни ТОЛЬКО текст сообщения, без кавычек и пояснений." % (c.get("name", "клиент"), trips_txt))
        text = agent_text(prompt)
        if text.startswith("__ERR__") or not text:
            errors.append({"client": c.get("name"), "error": text[7:] or "empty"})
            text = ("%s, с днём рождения! 🎉 Пусть год будет полон ярких путешествий. "
                    "Будем рады подобрать вам новое направление — напишите нам!" % c.get("name", ""))
        ph = "".join(ch for ch in str(c.get("phone", "")) if ch.isdigit() or ch == "+")
        d = {"phone": ph, "name": c.get("name"), "birthday": bd, "message": text,
             "created_at": time.strftime("%Y-%m-%d %H:%M"), "kind": "birthday", "status": "draft_ready"}
        drafts.append(d)
        try:
            api("/api/kv/set", {"key": "ta:draft:bday:%s:%s" % (target.strftime("%Y%m%d"), ph or c.get("name", "x")),
                                "value": json.dumps(d, ensure_ascii=False),
                                "description": "TA birthday draft %s" % c.get("name", ""), "global": True}, 30)
        except Exception as e:
            errors.append({"client": c.get("name"), "error": "kv:" + str(e)[:100]})
    if drafts and cfg.get("telegram_bot_token") and cfg.get("telegram_chat_id"):
        try:
            names = ", ".join(d.get("name", "?") for d in drafts[:10])
            note_msg = "🎂 Travel Agency: готово %s черновик(а) поздравлений с ДР (%s). Откройте панель (Plugins → Travel Agency) и нажмите «Отправить»." % (len(drafts), names)
            body = json.dumps({"chat_id": cfg["telegram_chat_id"], "text": note_msg, "disable_web_page_preview": True}).encode("utf-8")
            req = urllib.request.Request("https://api.telegram.org/bot%s/sendMessage" % cfg["telegram_bot_token"],
                                         data=body, headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=15, context=ctx)
        except Exception as e:
            errors.append({"client": "_tg_notify", "error": str(e)[:100]})
    return json.dumps({"status": "success", "date": str(target), "found": len(drafts), "drafts": drafts,
                       "errors": errors, "note": "Черновики готовы. Отправляет менеджер."}, ensure_ascii=False)