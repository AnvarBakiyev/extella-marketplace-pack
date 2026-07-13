# expert: ta_tv_search
# description: Travel Agency pack: full async tour search on Tourvisor (start -> poll status -> results). Params: departure_id, country_id, date_from/date_to (YYYY-MM-DD), nights_from/nights_to, adults, childs_json (ages array), price_from/price_to, currency, hotel_category, only_charter, limit, max_wait sec, jwt (fallback config). Returns compact hotel list with prices.

def ta_tv_search(departure_id=0, country_id=0, date_from="", date_to="", nights_from=7, nights_to=10,
                 adults=2, childs_json="[]", price_from=0, price_to=0, currency="KZT",
                 hotel_category=0, hotel_rating=0, only_charter=0, limit=25, max_wait=45, jwt="") -> str:
    import json, os, ssl, time, urllib.request, urllib.parse

    def _i(v, d=0):
        try:
            return int(float(v))
        except Exception:
            return d

    token = jwt if jwt and not str(jwt).startswith("{{") else ""
    if not token:
        try:
            cfg = json.load(open(os.path.expanduser("~/extella_wizard/app/config.json"), encoding="utf-8"))
            token = cfg.get("tourvisor_jwt", "")
        except Exception:
            token = ""
    if not token:
        return json.dumps({"status": "error", "error": "no_tourvisor_jwt"}, ensure_ascii=False)

    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    BASE = "https://api.tourvisor.ru/search/api/v1"

    def _get(path, pairs=None):
        qs = urllib.parse.urlencode(pairs or [])
        url = BASE + path + (("?" + qs) if qs else "")
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token, "User-Agent": "ExtellaTA/1.0"})
        with urllib.request.urlopen(req, timeout=25, context=ctx) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))

    dep = _i(departure_id); cty = _i(country_id)
    if not dep or not cty or not date_from or str(date_from).startswith("{{") or not date_to or str(date_to).startswith("{{"):
        return json.dumps({"status": "error", "error": "required: departure_id, country_id, date_from, date_to (YYYY-MM-DD)"}, ensure_ascii=False)
    try:
        childs = json.loads(childs_json) if childs_json and not str(childs_json).startswith("{{") else []
        if not isinstance(childs, list):
            childs = []
    except Exception:
        childs = []
    cur = currency if currency and not str(currency).startswith("{{") else "KZT"

    pairs = [("departureId", dep), ("countryId", cty), ("dateFrom", str(date_from)), ("dateTo", str(date_to)),
             ("nightsFrom", max(1, min(_i(nights_from, 7), 28))), ("nightsTo", max(1, min(_i(nights_to, 10), 28))),
             ("adults", max(1, min(_i(adults, 2), 6))), ("currency", cur),
             ("onlyCharter", "true" if _i(only_charter) else "false")]
    for age in childs[:3]:
        pairs.append(("childs", _i(age)))
    if _i(price_from):
        pairs.append(("priceFrom", _i(price_from)))
    if _i(price_to):
        pairs.append(("priceTo", _i(price_to)))
    if _i(hotel_category):
        pairs.append(("hotelCategory", _i(hotel_category)))
    if _i(hotel_rating):
        pairs.append(("hotelRating", _i(hotel_rating)))

    log = []
    try:
        start = _get("/tours/search", pairs)
        sid = start.get("searchId") if isinstance(start, dict) else None
        if not sid:
            return json.dumps({"status": "error", "error": "no searchId", "response": start}, ensure_ascii=False)
        log.append("searchId=%s" % sid)
        waited = 0; progress = 0; min_price = None
        wait_cap = max(10, min(_i(max_wait, 45), 120))
        while waited < wait_cap:
            time.sleep(3); waited += 3
            try:
                st = _get("/tours/search/%s/status" % sid)
                progress = st.get("progress", 0) if isinstance(st, dict) else 0
                min_price = st.get("minPrice", min_price) if isinstance(st, dict) else min_price
            except Exception as e:
                log.append("status_err:" + str(e)[:80])
            if progress >= 100:
                break
        log.append("progress=%s waited=%ss" % (progress, waited))
        res = _get("/tours/search/%s" % sid, [("limit", max(1, min(_i(limit, 25), 100)))])
        hotels = []
        for h in (res if isinstance(res, list) else []):
            tours = h.get("tours") or []
            best = min(tours, key=lambda t: t.get("price", 10**12)) if tours else {}
            hotels.append({
                "hotelId": h.get("id"), "name": h.get("name"), "stars": h.get("category"),
                "rating": h.get("rating"), "region": (h.get("region") or {}).get("name"),
                "price": h.get("price"), "currency": h.get("currency") or best.get("currency") or cur,
                "link": h.get("hotelDescriptionLink") or h.get("picturelink") or "",
                "picture": h.get("picturelink") or "",
                "bestTour": {"date": best.get("date"), "nights": best.get("nights"),
                             "meal": best.get("meal"), "price": best.get("price"),
                             "operator": best.get("operatorName") or best.get("operatorId")} if best else {},
                "toursCount": len(tours),
            })
        hotels.sort(key=lambda x: x.get("price") or 10**12)
        return json.dumps({"status": "success", "searchId": sid, "progress": progress, "minPrice": min_price,
                           "count": len(hotels), "hotels": hotels, "log": log}, ensure_ascii=False)
    except Exception as e:
        msg = str(e)[:300]
        hint = "jwt_expired_or_invalid: renew token in pro.tourvisor.ru cabinet" if "401" in msg else ""
        return json.dumps({"status": "error", "error": msg, "hint": hint, "log": log}, ensure_ascii=False)