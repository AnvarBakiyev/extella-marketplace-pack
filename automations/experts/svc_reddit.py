# expert: svc_reddit
# description: Service: fresh posts from Reddit subreddits (competitor/product discussions). RSS via old.reddit.com. Params: subreddits (comma-separated), sort (top/hot/new), t (day/week/month), per_sub (posts per subreddit, default 4).

def svc_reddit(subreddits="LocalLLaMA,artificial", sort="top", t="day", per_sub=4) -> str:
    import json, re, urllib.request, ssl
    from xml.etree import ElementTree as ET
    if not subreddits or str(subreddits).startswith("{{"):
        subreddits = "LocalLLaMA,artificial"
    sort = (str(sort) if sort and not str(sort).startswith("{{") else "top").strip().lower()
    if sort not in ("top", "hot", "new", "rising"):
        sort = "top"
    t = (str(t) if t and not str(t).startswith("{{") else "day").strip().lower()
    try:
        per = int(per_sub)
    except Exception:
        per = 4
    per = max(1, min(per, 15))
    subs = [s.strip().lstrip("r/").strip("/") for s in (subreddits if isinstance(subreddits, list) else str(subreddits).split(",")) if str(s).strip()]
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    ua = "ExtellaSvc/1.0 (competitor-intel; contact via extella.ai)"
    items = []; errors = []

    def _txt(node, *tags):
        for tag in tags:
            el = node.find(tag)
            if el is not None and (el.text or "").strip():
                return el.text.strip()
        return ""

    import time
    for _i, sub in enumerate(subs[:20]):
        if _i:
            time.sleep(1.2)  # gentler on the Reddit rate limit (429)
        url = "https://old.reddit.com/r/%s/%s/.rss?t=%s&limit=%d" % (sub, sort, t, per)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua})
            raw = urllib.request.urlopen(req, timeout=20, context=ctx).read()
            root = ET.fromstring(raw)
            for el in root.iter():  # strip namespaces
                if "}" in el.tag:
                    el.tag = el.tag.split("}", 1)[1]
            entries = root.findall(".//entry") or root.findall(".//item")
            for e in entries[:per]:
                link = _txt(e, "link")
                if not link:
                    le = e.find("link")
                    link = le.get("href") if le is not None else ""
                items.append({
                    "source": "reddit",
                    "subreddit": sub,
                    "title": _txt(e, "title"),
                    "date": _txt(e, "updated", "published", "pubDate"),
                    "url": link,
                    "text": re.sub("<[^>]+>", " ", _txt(e, "content", "summary", "description"))[:500].strip(),
                })
        except Exception as e:
            errors.append({"subreddit": sub, "error": str(e)[:120]})
    return json.dumps({"status": "success", "count": len(items), "items": items, "errors": errors}, ensure_ascii=False)