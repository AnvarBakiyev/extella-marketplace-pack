# expert: lp_wa_send
# description: Contract agent: send a WhatsApp message via GreenAPI to a client/counterparty (human-triggered from panel; not for cold mass mailing - ban risk). Params: phone (+7701...), text, id_instance/api_token_instance (fallback: greenapi_id/greenapi_token in config).

def lp_wa_send(phone="", text="", id_instance="", api_token_instance="") -> str:
    import json, os, ssl, urllib.request

    try:
        cfg = json.load(open(os.path.join(os.environ.get("EXTELLA_WIZARD_ROOT") or os.path.expanduser("~/extella_wizard"), "app", "config.json"), encoding="utf-8"))
    except Exception:
        cfg = {}
    iid = id_instance if id_instance and not str(id_instance).startswith("{{") else cfg.get("greenapi_id", "")
    gtok = api_token_instance if api_token_instance and not str(api_token_instance).startswith("{{") else cfg.get("greenapi_token", "")
    if not iid or not gtok:
        return json.dumps({"status": "error", "error": "no_greenapi_credentials",
                           "hint": "idInstance/apiTokenInstance с green-api.com, отсканируйте QR номером компании"}, ensure_ascii=False)
    msg = text if text and not str(text).startswith("{{") else ""
    ph = "".join(ch for ch in str(phone) if ch.isdigit())
    if not ph or not msg:
        return json.dumps({"status": "error", "error": "phone and text required"}, ensure_ascii=False)
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    url = "https://api.green-api.com/waInstance%s/sendMessage/%s" % (iid, gtok)
    body = json.dumps({"chatId": ph + "@c.us", "message": msg}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=25, context=ctx) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
        return json.dumps({"status": "success" if data.get("idMessage") else "error",
                           "id": data.get("idMessage"), "error": "" if data.get("idMessage") else str(data)[:200]},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)[:200]}, ensure_ascii=False)