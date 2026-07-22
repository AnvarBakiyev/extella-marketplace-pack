# expert: ta_tv_get
# description: Travel Agency pack: low-level GET to Tourvisor Search API (api.tourvisor.ru/search/api/v1). Params: path (e.g. /departures), query_json (dict as JSON), jwt (optional; fallback to the current device's platform-native Extella account config key tourvisor_jwt), timeout.

def ta_tv_get(path="/departures", query_json="{}", jwt="", timeout=25) -> str:
    import json, os, ssl, urllib.request, urllib.parse
    if not path or str(path).startswith("{{"):
        path = "/departures"
    if not str(path).startswith("/"):
        path = "/" + str(path)
    try:
        q = json.loads(query_json) if query_json and not str(query_json).startswith("{{") else {}
        if not isinstance(q, dict):
            q = {}
    except Exception:
        q = {}
    token = jwt if jwt and not str(jwt).startswith("{{") else ""
    if not token:
        try:
            from extella_expert_bridge import account_config
            cfg = account_config()
            token = cfg.get("tourvisor_jwt", "")
        except Exception:
            token = ""
    if not token:
        return json.dumps({"status": "error", "error": "no_tourvisor_jwt: pass jwt or configure Tourvisor in Extella"}, ensure_ascii=False)
    try:
        t = int(timeout)
    except Exception:
        t = 25
    # flatten arrays into repeated query params (childs=[5,7] -> childs=5&childs=7)
    pairs = []
    for k, v in q.items():
        if isinstance(v, (list, tuple)):
            for item in v:
                pairs.append((k, str(item)))
        elif v is not None and v != "":
            pairs.append((k, str(v).lower() if isinstance(v, bool) else str(v)))
    qs = urllib.parse.urlencode(pairs)
    url = "https://api.tourvisor.ru/search/api/v1" + str(path) + (("?" + qs) if qs else "")
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token, "User-Agent": "ExtellaTA/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=t, context=ctx) as r:
            body = r.read().decode("utf-8", errors="replace")
            code = r.getcode()
        try:
            data = json.loads(body)
        except Exception:
            data = body[:2000]
        return json.dumps({"status": "success", "status_code": code, "url": url.split("?")[0], "data": data}, ensure_ascii=False)
    except Exception as e:
        msg = str(e)[:300]
        hint = "jwt_expired_or_invalid: renew token in pro.tourvisor.ru cabinet" if "401" in msg else ""
        return json.dumps({"status": "error", "error": msg, "hint": hint, "url": url.split("?")[0]}, ensure_ascii=False)
