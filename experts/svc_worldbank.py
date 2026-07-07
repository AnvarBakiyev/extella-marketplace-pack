# expert: svc_worldbank
# description: Сервис: экономический показатель страны (по умолчанию ВВП). Источник World Bank. Параметры: country (KZ/RU/US), indicator (код, напр. NY.GDP.MKTP.CD).

def svc_worldbank(country="KZ", indicator="NY.GDP.MKTP.CD") -> str:
    import json, urllib.request, ssl
    country = "KZ" if (not country or str(country).startswith("{{")) else str(country).upper().strip()
    indicator = "NY.GDP.MKTP.CD" if (not indicator or str(indicator).startswith("{{")) else str(indicator).strip()
    try:
        ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
        u="https://api.worldbank.org/v2/country/%s/indicator/%s?format=json&per_page=1&mrv=1"%(country,indicator)
        d=json.loads(urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"ExtellaSvc/1.0"}),timeout=20,context=ctx).read())
        if not isinstance(d,list) or len(d)<2 or not d[1]: return json.dumps({"status":"error","message":"нет данных: "+country+"/"+indicator}, ensure_ascii=False)
        row=d[1][0]
        return json.dumps({"status":"success","country":row.get("country",{}).get("value",country),"indicator":row.get("indicator",{}).get("value",indicator),"year":row.get("date"),"value":row.get("value")}, ensure_ascii=False)
    except Exception as e: return json.dumps({"status":"error","message":str(e)[:120]}, ensure_ascii=False)