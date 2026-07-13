# expert: ta_pick_226
# description: Travel Agency pack: deterministic 2+2+2 offer selection from ta_tv_search results by client budget (2 within budget band, 2 below, 2 above). Params: results_json (output of ta_tv_search or its hotels array), budget (number), band_pct (budget tolerance percent, default 15).

def ta_pick_226(results_json="{}", budget=0, band_pct=15) -> str:
    import json

    def _f(v, d=0.0):
        try:
            return float(v)
        except Exception:
            return d

    try:
        data = json.loads(results_json) if isinstance(results_json, str) else results_json
    except Exception:
        return json.dumps({"status": "error", "error": "results_json is not valid JSON"}, ensure_ascii=False)
    hotels = data.get("hotels") if isinstance(data, dict) else data
    if not isinstance(hotels, list) or not hotels:
        return json.dumps({"status": "error", "error": "no hotels in results"}, ensure_ascii=False)
    b = _f(budget)
    if str(budget).startswith("{{"):
        b = 0.0

    priced_all = [h for h in hotels if _f(h.get("price"))]
    priced_all.sort(key=lambda h: _f(h.get("price")))
    if not priced_all:
        return json.dumps({"status": "error", "error": "no priced hotels in results"}, ensure_ascii=False)

    # Бюджет не задан -> подборка с разбросом по цене (2 дешёвых, 2 средних, 2 дорогих)
    if not b:
        n = len(priced_all)
        if n <= 6:
            spread = priced_all[:]
        else:
            idxs = sorted(set([0, 1, n // 2 - 1, n // 2, n - 2, n - 1]))
            idxs = [i for i in idxs if 0 <= i < n][:6]
            spread = [priced_all[i] for i in idxs]
        picks = []
        for h in spread[:6]:
            h = dict(h); h["bucket"] = "spread"; picks.append(h)
        return json.dumps({"status": "success", "budget": 0, "no_budget": True,
                           "counts": {"total": len(picks)}, "picks": picks}, ensure_ascii=False)

    band = max(1.0, min(_f(band_pct, 15), 50)) / 100.0
    lo, hi = b * (1 - band), b * (1 + band)

    priced = [h for h in hotels if _f(h.get("price"))]
    priced.sort(key=lambda h: _f(h.get("price")))
    within = [h for h in priced if lo <= _f(h.get("price")) <= hi]
    below = [h for h in priced if _f(h.get("price")) < lo]
    above = [h for h in priced if _f(h.get("price")) > hi]

    # within: closest to budget; below: most expensive of the cheap (best value); above: cheapest of the pricey
    within.sort(key=lambda h: abs(_f(h.get("price")) - b))
    below.sort(key=lambda h: -_f(h.get("price")))
    above.sort(key=lambda h: _f(h.get("price")))

    picks, used = [], set()

    def _take(pool, n, tag):
        got = 0
        for h in pool:
            key = h.get("hotelId") or h.get("name")
            if key in used:
                continue
            used.add(key); h = dict(h); h["bucket"] = tag
            picks.append(h); got += 1
            if got >= n:
                break
        return got

    got_w = _take(within, 2, "in_budget")
    got_b = _take(below, 2, "below_budget")
    got_a = _take(above, 2, "above_budget")
    # backfill to 6 from whatever is closest to budget
    if len(picks) < 6:
        rest = sorted([h for h in priced if (h.get("hotelId") or h.get("name")) not in used],
                      key=lambda h: abs(_f(h.get("price")) - b))
        for h in rest[:6 - len(picks)]:
            used.add(h.get("hotelId") or h.get("name")); h = dict(h); h["bucket"] = "closest"
            picks.append(h)
    order = {"below_budget": 0, "in_budget": 1, "closest": 2, "above_budget": 3}
    picks.sort(key=lambda h: (order.get(h.get("bucket"), 2), _f(h.get("price"))))
    return json.dumps({"status": "success", "budget": b, "band": [int(lo), int(hi)],
                       "counts": {"in_budget": got_w, "below": got_b, "above": got_a, "total": len(picks)},
                       "picks": picks}, ensure_ascii=False)