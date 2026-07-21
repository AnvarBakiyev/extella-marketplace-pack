# expert: svc_hackernews
# description: Сервис: топ технологических новостей Hacker News (заголовки + ссылки). Параметр: count.

def svc_hackernews(count="5") -> str:
    import json, urllib.request, ssl
    count = "5" if (not count or str(count).startswith("{{")) else str(count)
    try: n=max(1,min(15,int(count)))
    except Exception: n=5
    try:
        ctx=ssl.create_default_context()
        ids=json.loads(urllib.request.urlopen(urllib.request.Request("https://hacker-news.firebaseio.com/v0/topstories.json",headers={"User-Agent":"ExtellaSvc/1.0"}),timeout=20,context=ctx).read())[:n]
        items=[]
        for i in ids:
            it=json.loads(urllib.request.urlopen(urllib.request.Request("https://hacker-news.firebaseio.com/v0/item/%s.json"%i,headers={"User-Agent":"ExtellaSvc/1.0"}),timeout=20,context=ctx).read())
            items.append({"title":it.get("title"),"score":it.get("score"),"url":it.get("url") or ("https://news.ycombinator.com/item?id=%s"%i)})
        return json.dumps({"status":"success","count":len(items),"stories":items}, ensure_ascii=False)
    except Exception as e: return json.dumps({"status":"error","message":str(e)[:120]}, ensure_ascii=False)