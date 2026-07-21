# expert: ta_run_lead_pipeline
# description: Travel Agency pack orchestrator: lead answers -> resolve country in Tourvisor dictionaries -> async tour search -> 2+2+2 budget picks -> WhatsApp-ready draft. Saves lead and draft to KV (CRM stub), returns the draft. Human sends the message (F2: drafts only). Params: phone, fio, channel, direction (country name text), date_from/date_to, nights_from/nights_to, adults, childs_json, budget, currency, departure_id (default from KV ta:config), agency_name, manager_name, api_token.

def ta_run_lead_pipeline(phone="", fio="", channel="whatsapp", direction="", date_from="", date_to="",
                         nights_from=7, nights_to=10, adults=2, childs_json="[]", budget=0,
                         currency="", departure_id=0, agency_name="", manager_name="", api_token="") -> str:
    import json, os, ssl, ast, time, urllib.request

    tok = api_token if api_token and not str(api_token).startswith("{{") else ""
    cfg = {}
    try:
        cfg = json.load(open(os.path.join(os.environ.get("EXTELLA_WIZARD_ROOT") or os.path.expanduser("~/extella_wizard"), "app", "config.json"), encoding="utf-8"))
    except Exception:
        cfg = {}
    if not tok:
        tok = cfg.get("auth_token", "")
    if not tok:
        return json.dumps({"status": "error", "error": "no_api_token"}, ensure_ascii=False)

    ctx = ssl.create_default_context()
    HDR = {"X-Auth-Token": tok, "Content-Type": "application/json", "X-Profile-Id": "default",
           "X-Agent-Id": cfg.get("agent_id", "__EXTELLA_AGENT__") if isinstance(cfg, dict) else "__EXTELLA_AGENT__"}

    def api(path, payload, timeout=180):
        req = urllib.request.Request("https://api.extella.ai" + path, data=json.dumps(payload).encode("utf-8"),
                                     headers=HDR, method="POST")
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return json.loads(r.read().decode("utf-8"))

    def call_expert(name, params, timeout=180):
        out = api("/api/expert/run", {"expert_name": name, "params": params, "global": True}, timeout)
        # platform may defer long runs: poll /api/tasks/check until finished
        if isinstance(out, dict) and out.get("task_id") and "deferred" in str(out.get("result", "")).lower():
            tid = out["task_id"]; waited = 0
            while waited < timeout:
                time.sleep(5); waited += 5
                try:
                    st = api("/api/tasks/check", {"task_id": tid}, 30)
                except Exception:
                    continue
                if str(st.get("status", "")).lower() in ("completed", "success", "done", "error", "failed"):
                    out = st
                    break
            else:
                return {"status": "error", "error": "deferred task timeout: %s" % name, "task_id": tid}
        res = out.get("result", out) if isinstance(out, dict) else out
        if isinstance(res, str):
            try:
                res = json.loads(res)
            except Exception:
                try:
                    res = ast.literal_eval(res)
                except Exception:
                    return {"status": "error", "error": "unparsable expert result", "raw": str(res)[:400]}
        if isinstance(res, dict) and "result" in res and isinstance(res["result"], str):
            inner = res["result"]
            try:
                return json.loads(inner)
            except Exception:
                try:
                    return ast.literal_eval(inner)
                except Exception:
                    return {"status": "error", "error": "unparsable inner result", "raw": inner[:400]}
        return res

    def kv_get(key):
        try:
            got = api("/api/kv/get", {"key": key, "global": True}, 30)
            return (got or {}).get("value") or ""
        except Exception:
            return ""

    stages = []
    # 0) pack config (departure city, currency, agency defaults)
    ta_cfg = {}
    try:
        ta_cfg = json.loads(kv_get("ta:config") or "{}")
    except Exception:
        ta_cfg = {}
    dep = departure_id if departure_id and not str(departure_id).startswith("{{") else ta_cfg.get("departure_id", 0)
    cur = currency if currency and not str(currency).startswith("{{") else ta_cfg.get("currency", "KZT")
    agency = agency_name if agency_name and not str(agency_name).startswith("{{") else ta_cfg.get("agency_name", "")
    manager = manager_name if manager_name and not str(manager_name).startswith("{{") else ta_cfg.get("manager_name", "")

    # 1) save lead
    answers = {"direction": direction, "date_from": date_from, "date_to": date_to, "adults": adults,
               "childs": childs_json, "budget": budget}
    lead_res = call_expert("ta_lead_upsert", {"phone": phone, "fio": fio, "channel": channel,
                                              "answers_json": json.dumps(answers, ensure_ascii=False),
                                              "status": "qualified", "api_token": tok}, 60)
    stages.append({"stage": "lead_upsert", "ok": lead_res.get("status") == "success"})
    if lead_res.get("status") != "success":
        return json.dumps({"status": "error", "error": "lead_upsert failed", "detail": lead_res, "stages": stages}, ensure_ascii=False)

    # 2) resolve country by name in Tourvisor dictionary
    if not direction or str(direction).startswith("{{"):
        return json.dumps({"status": "error", "error": "direction (country name) required", "stages": stages}, ensure_ascii=False)
    dicts = call_expert("ta_tv_get", {"path": "/countries", "query_json": json.dumps({"departureId": dep} if dep else {})}, 60)
    country_id, country_name = 0, ""
    dl = dicts.get("data") if isinstance(dicts, dict) else None
    if isinstance(dl, list):
        low = str(direction).strip().lower()
        for c in dl:
            nm = str(c.get("name") or c.get("russianName") or "").lower()
            if low in nm or nm in low:
                country_id, country_name = c.get("id"), c.get("name") or c.get("russianName")
                break
    stages.append({"stage": "resolve_country", "ok": bool(country_id), "countryId": country_id, "country": country_name})
    if not country_id:
        opts = [c.get("name") for c in dl[:30]] if isinstance(dl, list) else []
        return json.dumps({"status": "error", "error": "country not found in Tourvisor dictionary: %s" % direction,
                           "available": opts, "stages": stages}, ensure_ascii=False)

    # 3) search
    sr = call_expert("ta_tv_search", {"departure_id": dep, "country_id": country_id, "date_from": date_from,
                                      "date_to": date_to, "nights_from": nights_from, "nights_to": nights_to,
                                      "adults": adults, "childs_json": childs_json, "currency": cur,
                                      "max_wait": 60, "limit": 40}, 240)
    stages.append({"stage": "tv_search", "ok": sr.get("status") == "success", "count": sr.get("count"), "progress": sr.get("progress")})
    if sr.get("status") != "success" or not sr.get("hotels"):
        return json.dumps({"status": "error", "error": "search failed or empty", "detail": {k: sr.get(k) for k in ("error", "hint", "log")},
                           "stages": stages}, ensure_ascii=False)

    # 4) 2+2+2 picks
    pk = call_expert("ta_pick_226", {"results_json": json.dumps(sr, ensure_ascii=False), "budget": budget}, 60)
    stages.append({"stage": "pick_226", "ok": pk.get("status") == "success", "counts": pk.get("counts")})
    if pk.get("status") != "success":
        return json.dumps({"status": "error", "error": "подбор не удался: " + str(pk.get("error", "")),
                           "detail": pk, "stages": stages}, ensure_ascii=False)

    # 5) message draft
    try:
        n_childs = len(json.loads(childs_json)) if childs_json and not str(childs_json).startswith("{{") else 0
    except Exception:
        n_childs = 0
    party = "%s взр." % adults + ((" + %s дет." % n_childs) if n_childs else "")
    dates_text = "с %s по %s" % (date_from, date_to)
    msg = call_expert("ta_offer_message", {"picks_json": json.dumps(pk, ensure_ascii=False), "client_name": fio,
                                           "direction": country_name, "dates_text": dates_text, "party_text": party,
                                           "budget": budget, "currency": cur, "agency_name": agency,
                                           "manager_name": manager}, 60)
    stages.append({"stage": "offer_message", "ok": msg.get("status") == "success"})

    # 6) store draft
    ph = "".join(ch for ch in str(phone) if ch.isdigit() or ch == "+")
    draft = {"phone": ph, "fio": fio, "channel": channel, "created_at": time.strftime("%Y-%m-%d %H:%M"),
             "message": msg.get("message", ""), "picks": pk.get("picks"), "searchId": sr.get("searchId"),
             "country": country_name, "budget": budget, "currency": cur, "status": "draft_ready"}
    try:
        api("/api/kv/set", {"key": "ta:draft:" + ph, "value": json.dumps(draft, ensure_ascii=False),
                            "description": "TA offer draft for %s (%s)" % (fio, ph), "global": True}, 30)
    except Exception as e:
        stages.append({"stage": "store_draft", "ok": False, "error": str(e)[:120]})
    call_expert("ta_lead_upsert", {"phone": ph, "status": "offered", "api_token": tok}, 60)

    return json.dumps({"status": "success", "draft_kv": "ta:draft:" + ph, "message": msg.get("message", ""),
                       "picks_total": (pk.get("counts") or {}).get("total"), "stages": stages,
                       "note": "Черновик готов. Отправляет менеджер (режим F2: только черновики)."}, ensure_ascii=False)