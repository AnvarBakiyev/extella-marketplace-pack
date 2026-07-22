# expert: ta_tg_send
# description: Travel Agency pack: send a Telegram message via Bot API (manager notifications: new drafts ready, campaign results). Params: text, chat_id, bot_token (fallback: telegram_chat_id/telegram_bot_token in the current device's platform-native Extella account config).

def ta_tg_send(text="", chat_id="", bot_token="") -> str:
    import json, os, ssl, urllib.request

    try:
        from extella_expert_bridge import account_config
        cfg = account_config()
    except Exception:
        cfg = {}
    tok = bot_token if bot_token and not str(bot_token).startswith("{{") else cfg.get("telegram_bot_token", "")
    cid = chat_id if chat_id and not str(chat_id).startswith("{{") else cfg.get("telegram_chat_id", "")
    if not tok or not cid:
        return json.dumps({"status": "error", "error": "no_telegram_credentials",
                           "hint": "создайте бота у @BotFather, chat_id — через @userinfobot; сохраните в онбординге"}, ensure_ascii=False)
    msg = text if text and not str(text).startswith("{{") else ""
    if not msg:
        return json.dumps({"status": "error", "error": "text required"}, ensure_ascii=False)
    ctx = ssl.create_default_context()
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