# expert: svc_postal
# description: Сервис: населённый пункт по почтовому индексу. Источник Zippopotam. Параметры: country (us/de/ru...), code.

def svc_postal(country="us", code="90210") -> str:
    import json, urllib.request, ssl
    country = "us" if (not country or str(country).startswith("{{")) else str(country).lower().strip()
    code = "90210" if (not code or str(code).startswith("{{")) else str(code).strip()
    try:
        ctx=ssl.create_default_context()
        d=json.loads(urllib.request.urlopen(urllib.request.Request("https://api.zippopotam.us/%s/%s"%(country,code),headers={"User-Agent":"ExtellaSvc/1.0"}),timeout=20,context=ctx).read())
        pl=(d.get("places") or [])
        if not pl: return json.dumps({"status":"error","message":"индекс не найден"}, ensure_ascii=False)
        return json.dumps({"status":"success","country":d.get("country"),"code":code,"place":pl[0].get("place name"),"state":pl[0].get("state")}, ensure_ascii=False)
    except Exception as e: return json.dumps({"status":"error","message":str(e)[:120]}, ensure_ascii=False)