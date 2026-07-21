# expert: svc_holidays
# description: Сервис: государственные праздники и выходные страны за год. Источник Nager.Date. Параметры: country (KZ/RU/US...), year.

def svc_holidays(country="KZ", year="2026") -> str:
    import json, urllib.request, ssl
    country = "KZ" if (not country or str(country).startswith("{{")) else str(country).upper().strip()
    year = "2026" if (not year or str(year).startswith("{{")) else str(year).strip()
    try:
        ctx=ssl.create_default_context()
        d=json.loads(urllib.request.urlopen(urllib.request.Request("https://date.nager.at/api/v3/PublicHolidays/%s/%s"%(year,country),headers={"User-Agent":"ExtellaSvc/1.0"}),timeout=20,context=ctx).read())
        if not isinstance(d,list) or not d: return json.dumps({"status":"error","message":"нет данных по "+country+"/"+year}, ensure_ascii=False)
        items=[{"date":h.get("date"),"name":h.get("localName") or h.get("name")} for h in d]
        return json.dumps({"status":"success","country":country,"year":year,"count":len(items),"holidays":items}, ensure_ascii=False)
    except Exception as e: return json.dumps({"status":"error","message":str(e)[:120]}, ensure_ascii=False)