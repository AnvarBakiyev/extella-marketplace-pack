# expert: ta_offer_message
# description: Travel Agency pack: deterministic WhatsApp-ready offer message in Russian from 2+2+2 picks. Params: picks_json (output of ta_pick_226), client_name, direction (country/resort text), dates_text, party_text (e.g. "2 vzroslykh + rebenok 7 let"), budget, currency, agency_name, manager_name.

def ta_offer_message(picks_json="{}", client_name="", direction="", dates_text="", party_text="",
                     budget=0, currency="KZT", agency_name="", manager_name="") -> str:
    import json

    def _fmt(n):
        try:
            return "{:,.0f}".format(float(n)).replace(",", " ")
        except Exception:
            return str(n)

    try:
        data = json.loads(picks_json) if isinstance(picks_json, str) else picks_json
    except Exception:
        return json.dumps({"status": "error", "error": "picks_json is not valid JSON"}, ensure_ascii=False)
    picks = data.get("picks") if isinstance(data, dict) else data
    if not isinstance(picks, list) or not picks:
        return json.dumps({"status": "error", "error": "no picks"}, ensure_ascii=False)

    cur = currency if currency and not str(currency).startswith("{{") else "KZT"
    name = client_name if client_name and not str(client_name).startswith("{{") else ""
    lines = []
    lines.append(("%s, здравствуйте! 👋" % name) if name else "Здравствуйте! 👋")
    intro = "Подобрали для вас варианты"
    if direction and not str(direction).startswith("{{"):
        intro += " — %s" % direction
    if dates_text and not str(dates_text).startswith("{{"):
        intro += ", %s" % dates_text
    if party_text and not str(party_text).startswith("{{"):
        intro += " (%s)" % party_text
    lines.append(intro + ":")
    lines.append("")

    labels = {"below_budget": "💚 Выгоднее бюджета", "in_budget": "🎯 В вашем бюджете",
              "above_budget": "⭐ Чуть дороже, но стоит того", "closest": "🎯 Ближе всего к бюджету",
              "spread": "✨ Варианты на выбор"}
    last_bucket = None
    for h in picks[:6]:
        b = h.get("bucket")
        if b != last_bucket:
            lines.append(labels.get(b, "Варианты") + ":")
            last_bucket = b
        stars = "★" * int(h.get("stars") or 0)
        bt = h.get("bestTour") or {}
        piece = "• %s %s (%s)" % (h.get("name", "Отель"), stars, h.get("region") or "")
        details = []
        if bt.get("nights"):
            details.append("%s ноч." % bt["nights"])
        if bt.get("date"):
            details.append("вылет %s" % bt["date"])
        if h.get("rating"):
            details.append("рейтинг %s" % h["rating"])
        if details:
            piece += " — " + ", ".join(details)
        piece += " — от %s %s" % (_fmt(h.get("price")), h.get("currency") or cur)
        lines.append(piece)
        if h.get("link"):
            lines.append("  %s" % h["link"])
    lines.append("")
    try:
        bnum = float(budget)
    except Exception:
        bnum = 0
    if bnum:
        lines.append("Ориентировались на бюджет ~%s %s." % (_fmt(bnum), cur))
    lines.append("Какой вариант посмотреть подробнее? Могу проверить актуальную цену и места на рейсе ✈️")
    sig = []
    if manager_name and not str(manager_name).startswith("{{"):
        sig.append(manager_name)
    if agency_name and not str(agency_name).startswith("{{"):
        sig.append(agency_name)
    if sig:
        lines.append("— " + ", ".join(sig))
    msg = "\n".join(lines)
    return json.dumps({"status": "success", "message": msg, "options": len(picks[:6])}, ensure_ascii=False)