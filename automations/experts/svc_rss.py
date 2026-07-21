# expert: svc_rss
# description: Service: fresh entries from RSS/Atom feeds (competitor blogs, changelogs). Params: feeds (comma-separated URLs), per_feed (entries per feed, default 3).

def svc_rss(feeds="https://hnrss.org/frontpage", per_feed=3) -> str:
    import json, re, urllib.request, ssl
    from xml.etree import ElementTree as ET
    if not feeds or str(feeds).startswith("{{"):
        feeds = "https://hnrss.org/frontpage"
    try:
        per = int(per_feed)
    except Exception:
        per = 3
    per = max(1, min(per, 10))
    feed_list = [f.strip() for f in (feeds if isinstance(feeds, list) else str(feeds).split(",")) if str(f).strip()]
    ctx = ssl.create_default_context()
    items = []; errors = []

    def _txt(node, *tags):
        for t in tags:
            el = node.find(t)
            if el is not None and (el.text or "").strip():
                return el.text.strip()
        return ""

    for feed in feed_list[:25]:
        try:
            req = urllib.request.Request(feed, headers={"User-Agent": "ExtellaSvc/1.0"})
            raw = urllib.request.urlopen(req, timeout=20, context=ctx).read()
            root = ET.fromstring(raw)
            for el in root.iter():  # strip namespaces
                if "}" in el.tag:
                    el.tag = el.tag.split("}", 1)[1]
            entries = root.findall(".//item") or root.findall(".//entry")
            for e in entries[:per]:
                link = _txt(e, "link")
                if not link:
                    le = e.find("link")
                    link = le.get("href") if le is not None else ""
                items.append({
                    "source": "rss",
                    "feed": feed,
                    "title": _txt(e, "title"),
                    "date": _txt(e, "pubDate", "published", "updated"),
                    "url": link,
                    "text": re.sub("<[^>]+>", "", _txt(e, "description", "summary", "content"))[:600],
                })
        except Exception as e:
            errors.append({"feed": feed, "error": str(e)[:120]})
    return json.dumps({"status": "success", "count": len(items), "items": items, "errors": errors}, ensure_ascii=False)