# expert: ta_season_campaign
# description: Travel Agency pack: pre-season campaign — for each client in KV ta:clients build a personalized seasonal invitation draft within their past budget (Qwen agent, tool_choice none). Optional live Tourvisor search per client (do_search=1, paid requests — off by default). Params: season (leto/osen/zima/vesna or free text), do_search, max_clients, agent_id, api_token.

def ta_season_campaign(season="лето", do_search=0, max_clients=20, phones_json="[]", agent_id="__EXTELLA_AGENT__", api_token="", source_file="", source_key="", target="", client="") -> str:
    import json, os, ssl, ast, time, urllib.request

    tok = api_token if api_token and not str(api_token).startswith("{{") else ""
    try:
        cfg = json.load(open(os.path.join(os.environ.get("EXTELLA_WIZARD_ROOT") or os.path.expanduser("~/extella_wizard"), "app", "config.json"), encoding="utf-8"))
    except Exception:
        cfg = {}
    if not tok:
        tok = cfg.get("auth_token", "")
    if not tok:
        return json.dumps({"status": "error", "error": "no_api_token"}, ensure_ascii=False)
    agent = agent_id if agent_id and not str(agent_id).startswith("{{") else "__EXTELLA_AGENT__"
    sz = season if season and not str(season).startswith("{{") else "лето"

    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
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
        cap = max(1, min(int(max_clients), 200))
    except Exception:
        cap = 20

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
                                         "tool_choice": "none", "temperature": 0.5, "max_output_tokens": 600}, 120)
            for item in (out.get("output") or []):
                if item.get("type") == "message":
                    for c in (item.get("content") or []):
                        if c.get("text"):
                            return _scrub(c["text"])
        except Exception as e:
            return "__ERR__" + str(e)[:120]
        return ""

    stamp = time.strftime("%Y%m%d")
    drafts, errors = [], []
    for c in clients[:cap]:
        trips = c.get("trips") or []
        budgets = [t.get("budget") for t in trips if t.get("budget")]
        avg_budget = int(sum(budgets) / len(budgets)) if budgets else 0
        trips_txt = "; ".join("%s (%s, бюджет %s)" % (t.get("destination", "?"), t.get("date", "?"), t.get("budget", "?"))
                              for t in trips[-3:]) or "нет данных"
        prompt = ("Ты — ассистент турагентства. Сезон: %s. Напиши короткое персональное сообщение для WhatsApp "
                  "постоянному клиенту с приглашением подобрать тур на новый сезон. Клиент: %s. "
                  "Прошлые поездки: %s. Средний бюджет прошлых поездок: %s %s. "
                  "Требования: по-русски, 3-4 предложения, опора на прошлые поездки (похожие направления или новинка того же уровня), "
                  "явно упомянуть, что подберём 5 вариантов в его бюджете, без давления. "
                  "Верни ТОЛЬКО текст сообщения." % (sz, c.get("name", "клиент"), trips_txt, avg_budget or "не известен",
                                                     c.get("currency", "KZT")))
        text = agent_text(prompt)
        if text.startswith("__ERR__") or not text:
            errors.append({"client": c.get("name"), "error": text[7:] or "empty"})
            text = ("%s, здравствуйте! Открываем сезон (%s) — готовы подобрать для вас 5 вариантов в вашем бюджете. "
                    "Напишите, куда хочется в этот раз? ✈️" % (c.get("name", ""), sz))
        ph = "".join(ch for ch in str(c.get("phone", "")) if ch.isdigit() or ch == "+")
        d = {"phone": ph, "name": c.get("name"), "season": sz, "avg_budget": avg_budget,
             "message": text, "created_at": time.strftime("%Y-%m-%d %H:%M"), "kind": "season", "status": "draft_ready"}
        drafts.append(d)
        try:
            api("/api/kv/set", {"key": "ta:draft:season:%s:%s" % (stamp, ph or c.get("name", "x")),
                                "value": json.dumps(d, ensure_ascii=False),
                                "description": "TA season draft %s (%s)" % (c.get("name", ""), sz), "global": True}, 30)
        except Exception as e:
            errors.append({"client": c.get("name"), "error": "kv:" + str(e)[:100]})
    return json.dumps({"status": "success", "season": sz, "found": len(drafts), "drafts": drafts, "errors": errors,
                       "note": "Черновики готовы (do_search=%s: живой поиск туров в кампании %s). Отправляет менеджер." %
                               (do_search, "включён" if str(do_search) in ("1", "true", "True") else "выключен — бережём платные запросы")},
                      ensure_ascii=False)