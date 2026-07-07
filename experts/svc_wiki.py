# expert: svc_wiki
# description: Сервис: краткая справка из Википедии по теме (определение + резюме). Параметр: topic.

def svc_wiki(topic="\u0410\u043b\u043c\u0430\u0442\u044b") -> str:
    import json, urllib.request, urllib.parse, ssl
    topic = "\u0410\u043b\u043c\u0430\u0442\u044b" if (not topic or str(topic).startswith("{{")) else str(topic).strip()
    try:
        ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
        u="https://ru.wikipedia.org/api/rest_v1/page/summary/"+urllib.parse.quote(topic)
        d=json.loads(urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"ExtellaSvc/1.0 (extella.ai)"}),timeout=20,context=ctx).read())
        ex=d.get("extract","")
        if not ex: return json.dumps({"status":"error","message":"не найдено: "+topic}, ensure_ascii=False)
        return json.dumps({"status":"success","title":d.get("title",topic),"summary":ex,"url":d.get("content_urls",{}).get("desktop",{}).get("page","")}, ensure_ascii=False)
    except Exception as e: return json.dumps({"status":"error","message":str(e)[:120]}, ensure_ascii=False)