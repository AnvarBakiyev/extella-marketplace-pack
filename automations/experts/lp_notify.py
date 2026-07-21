# expert: lp_notify
# description: Contract-agent pack: notify the manager/head in Telegram (contract review summary ready, negotiation draft awaiting approval). Params: text, chat_id, bot_token (fallback: telegram_chat_id/telegram_bot_token in ~/extella_wizard/app/config.json).

def lp_notify(text="", chat_id="", bot_token="") -> str:
    import json, os, ssl, urllib.request

    try:
        cfg = json.load(open(os.path.join(os.environ.get("EXTELLA_WIZARD_ROOT") or os.path.expanduser("~/extella_wizard"), "app", "config.json"), encoding="utf-8"))
    except Exception:
        cfg = {}
    tok = bot_token if bot_token and not str(bot_token).startswith("{{") else cfg.get("telegram_bot_token", "")
    cid = chat_id if chat_id and not str(chat_id).startswith("{{") else cfg.get("telegram_chat_id", "")
    if not tok or not cid:
        return json.dumps({"status": "error", "error": "no_telegram_credentials",
                           "hint": "создайте бота у @BotFather, chat_id — через @userinfobot; сохраните в панели"}, ensure_ascii=False)
    msg = text if text and not str(text).startswith("{{") else ""
    if not msg:
        return json.dumps({"status": "error", "error": "text required"}, ensure_ascii=False)
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    url = "https://api.telegram.org/bot%s/sendMessage" % tok
    body = json.dumps({"chat_id": cid, "text": msg[:4000], "disable_web_page_preview": True}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
        return json.dumps({"status": "success" if data.get("ok") else "error",
                           "message_id": (data.get("result") or {}).get("message_id"),
                           "error": "" if data.get("ok") else str(data)[:200]}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)[:200]}, ensure_ascii=False)