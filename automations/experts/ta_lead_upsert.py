# expert: ta_lead_upsert
# description: Travel Agency pack: create/update a lead card in Extella KV (CRM stub until EON Travel API is available). Params: phone (required, id of lead), fio, channel (whatsapp/instagram/threads/email/telegram/direct), answers_json (direction/dates/adults/childs/budget), status (new/qualified/offered/handed_over), note, api_token (fallback config).

def ta_lead_upsert(phone="", fio="", channel="", answers_json="{}", status="", note="", api_token="") -> str:
    import json, os, ssl, time, urllib.request

    tok = api_token if api_token and not str(api_token).startswith("{{") else ""
    try:
        cfg = json.load(open(os.path.expanduser("~/extella_wizard/app/config.json"), encoding="utf-8"))
    except Exception:
        cfg = {}
    if not tok:
        tok = cfg.get("auth_token", "")
    if not tok:
        return json.dumps({"status": "error", "error": "no_api_token"}, ensure_ascii=False)
    ph = "".join(ch for ch in str(phone) if ch.isdigit() or ch == "+")
    if not ph or str(phone).startswith("{{"):
        return json.dumps({"status": "error", "error": "phone required"}, ensure_ascii=False)

    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    HDR = {"X-Auth-Token": tok, "Content-Type": "application/json", "X-Profile-Id": "default",
           "X-Agent-Id": cfg.get("agent_id", "__EXTELLA_AGENT__") if isinstance(cfg, dict) else "__EXTELLA_AGENT__"}

    def api(path, payload):
        req = urllib.request.Request("https://api.extella.ai" + path, data=json.dumps(payload).encode("utf-8"),
                                     headers=HDR, method="POST")
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            return json.loads(r.read().decode("utf-8"))

    key = "ta:lead:" + ph
    lead = {}
    try:
        got = api("/api/kv/get", {"key": key, "global": True})
        raw = (got or {}).get("value") or ""
        if raw:
            lead = json.loads(raw)
    except Exception:
        lead = {}
    try:
        answers = json.loads(answers_json) if answers_json and not str(answers_json).startswith("{{") else {}
        if not isinstance(answers, dict):
            answers = {}
    except Exception:
        answers = {}

    lead.setdefault("phone", ph)
    lead.setdefault("created_at", time.strftime("%Y-%m-%d %H:%M"))
    if fio and not str(fio).startswith("{{"):
        lead["fio"] = fio
    if channel and not str(channel).startswith("{{"):
        lead["channel"] = channel
    if answers:
        lead.setdefault("answers", {}).update(answers)
    if status and not str(status).startswith("{{"):
        lead["status"] = status
    elif "status" not in lead:
        lead["status"] = "new"
    if note and not str(note).startswith("{{"):
        lead.setdefault("notes", []).append({"at": time.strftime("%Y-%m-%d %H:%M"), "text": str(note)[:500]})
    lead["updated_at"] = time.strftime("%Y-%m-%d %H:%M")

    try:
        api("/api/kv/set", {"key": key, "value": json.dumps(lead, ensure_ascii=False),
                            "description": "TA lead %s %s [%s]" % (lead.get("fio", ""), ph, lead.get("status")), "global": True})
        # index of leads
        idx = []
        try:
            got = api("/api/kv/get", {"key": "ta:leads:index", "global": True})
            idx = json.loads((got or {}).get("value") or "[]")
        except Exception:
            idx = []
        if ph not in idx:
            idx.append(ph)
            api("/api/kv/set", {"key": "ta:leads:index", "value": json.dumps(idx),
                                "description": "TA leads phone index", "global": True})
        return json.dumps({"status": "success", "key": key, "lead": lead}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)[:300]}, ensure_ascii=False)