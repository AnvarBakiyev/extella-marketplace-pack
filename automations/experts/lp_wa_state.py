# expert: lp_wa_state
# description: Contract agent: check GreenAPI WhatsApp instance state (authorized / notAuthorized). Params: id_instance, api_token_instance (fallback: greenapi_id/greenapi_token in the current device's platform-native Extella account config).

def lp_wa_state(id_instance="", api_token_instance="") -> str:
    import json, os, ssl, urllib.request

    try:
        from extella_expert_bridge import account_config
        cfg = account_config()
    except Exception:
        cfg = {}
    iid = id_instance if id_instance and not str(id_instance).startswith("{{") else cfg.get("greenapi_id", "")
    tok = api_token_instance if api_token_instance and not str(api_token_instance).startswith("{{") else cfg.get("greenapi_token", "")
    if not iid or not tok:
        return json.dumps({"status": "error", "error": "no_greenapi_credentials",
                           "hint": "получите idInstance и apiTokenInstance на green-api.com, сохраните через онбординг"}, ensure_ascii=False)
    ctx = ssl.create_default_context()
    url = "https://api.green-api.com/waInstance%s/getStateInstance/%s" % (iid, tok)
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=20, context=ctx) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
        state = data.get("stateInstance", "")
        return json.dumps({"status": "success", "state": state, "authorized": state == "authorized",
                           "hint": "" if state == "authorized" else "отсканируйте QR в кабинете green-api.com этим номером WhatsApp"},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)[:200]}, ensure_ascii=False)