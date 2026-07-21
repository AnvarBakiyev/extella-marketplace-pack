# expert: svc_books
# description: Сервис: поиск книг (автор, год, издания) в Open Library. Параметр: query.

def svc_books(query="\u0412\u043e\u0439\u043d\u0430 \u0438 \u043c\u0438\u0440") -> str:
    import json, urllib.request, urllib.parse, ssl
    query = "\u0412\u043e\u0439\u043d\u0430 \u0438 \u043c\u0438\u0440" if (not query or str(query).startswith("{{")) else str(query).strip()
    try:
        ctx=ssl.create_default_context()
        u="https://openlibrary.org/search.json?"+urllib.parse.urlencode({"q":query,"limit":5,"fields":"title,author_name,first_publish_year"})
        d=json.loads(urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"ExtellaSvc/1.0"}),timeout=25,context=ctx).read())
        docs=d.get("docs") or []
        if not docs: return json.dumps({"status":"error","message":"ничего не найдено: "+query}, ensure_ascii=False)
        books=[{"title":b.get("title"),"author":(b.get("author_name") or [""])[0],"year":b.get("first_publish_year")} for b in docs]
        return json.dumps({"status":"success","query":query,"found":d.get("numFound"),"books":books}, ensure_ascii=False)
    except Exception as e: return json.dumps({"status":"error","message":str(e)[:120]}, ensure_ascii=False)