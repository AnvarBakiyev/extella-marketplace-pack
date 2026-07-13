# expert: ta_wa_send
# description: Travel Agency pack: send a WhatsApp message via GreenAPI (human-triggered from onboarding UI; not for cold mass mailing - ban risk). Params: phone (+7701...), text OR draft_key (KV key like ta:draft:<phone> - takes message from stored draft and marks it sent), id_instance/api_token_instance (fallback config), api_token (Extella, for KV ops).

def ta_wa_send(phone="", text="", draft_key="", id_instance="", api_token_instance="", api_token="") -> str:
    import json, os, ssl, time, urllib.request

    try:
        cfg = json.load(open(os.path.expanduser("~/extella_wizard/app/config.json"), encoding="utf-8"))
    except Exception:
        cfg = {}
    iid = id_instance if id_instance and not str(id_instance).startswith("{{") else cfg.get("greenapi_id", "")
    gtok = api_token_instance if api_token_instance and not str(api_token_instance).startswith("{{") else cfg.get("greenapi_token", "")
    if not iid or not gtok:
        return json.dumps({"status": "error", "error": "no_greenapi_credentials"}, ensure_ascii=False)
    xtok = api_token if api_token and not str(api_token).startswith("{{") else cfg.get("auth_token", "")

    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE

    def xapi(path, payload):
        req = urllib.request.Request("https://api.extella.ai" + path, data=json.dumps(payload).encode("utf-8"),
                                     headers={"X-Auth-Token": xtok, "Content-Type": "application/json",
                                              "X-Profile-Id": "default",
                                              "X-Agent-Id": cfg.get("agent_id", "__EXTELLA_AGENT__")}, method="POST")
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            return json.loads(r.read().decode("utf-8"))

    msg = text if text and not str(text).startswith("{{") else ""
    draft = None
    dk = draft_key if draft_key and not str(draft_key).startswith("{{") else ""
    if dk and not msg:
        try:
            got = xapi("/api/kv/get", {"key": dk, "global": True})
            draft = json.loads((got or {}).get("value") or "{}")
            msg = draft.get("message", "")
            if not phone or str(phone).startswith("{{"):
                phone = draft.get("phone", "")
        except Exception as e:
            return json.dumps({"status": "error", "error": "draft not found: " + str(e)[:120]}, ensure_ascii=False)
    ph = "".join(ch for ch in str(phone) if ch.isdigit())
    if not ph or not msg:
        return json.dumps({"status": "error", "error": "phone and text (or draft_key) required"}, ensure_ascii=False)

    url = "https://api.green-api.com/waInstance%s/sendMessage/%s" % (iid, gtok)
    body = json.dumps({"chatId": ph + "@c.us", "message": msg}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=25, context=ctx) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
        sent_id = data.get("idMessage", "")
        if dk and draft is not None and xtok:
            try:
                draft["status"] = "sent"; draft["sent_at"] = time.strftime("%Y-%m-%d %H:%M"); draft["wa_id"] = sent_id
                xapi("/api/kv/set", {"key": dk, "value": json.dumps(draft, ensure_ascii=False),
                                     "description": "TA draft (sent) %s" % ph, "global": True})
            except Exception:
                pass
        return json.dumps({"status": "success", "idMessage": sent_id, "to": ph}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)[:250],
                           "hint": "проверьте состояние инстанса (ta_wa_state) и формат номера"}, ensure_ascii=False)