# expert: svc_weather
# description: Сервис: текущая погода в городе (температура, ветер, влажность). Источник Open-Meteo. Параметр: city.

def svc_weather(city="\u0410\u043b\u043c\u0430\u0442\u044b") -> str:
    import json, urllib.request, urllib.parse, ssl
    city = "\u0410\u043b\u043c\u0430\u0442\u044b" if (not city or str(city).startswith("{{")) else str(city).strip()
    try:
        ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
        g=json.loads(urllib.request.urlopen(urllib.request.Request("https://geocoding-api.open-meteo.com/v1/search?"+urllib.parse.urlencode({"name":city,"count":1,"language":"ru"}),headers={"User-Agent":"ExtellaSvc/1.0"}),timeout=20,context=ctx).read())
        res=(g.get("results") or [])
        if not res: return json.dumps({"status":"error","message":"город не найден: "+city}, ensure_ascii=False)
        r=res[0]; lat=r["latitude"]; lon=r["longitude"]
        w=json.loads(urllib.request.urlopen(urllib.request.Request("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s&current=temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code"%(lat,lon),headers={"User-Agent":"ExtellaSvc/1.0"}),timeout=20,context=ctx).read())
        c=w.get("current",{})
        return json.dumps({"status":"success","city":r.get("name",city),"country":r.get("country",""),"temp_c":c.get("temperature_2m"),"humidity_pct":c.get("relative_humidity_2m"),"wind_ms":c.get("wind_speed_10m")}, ensure_ascii=False)
    except Exception as e: return json.dumps({"status":"error","message":str(e)[:120]}, ensure_ascii=False)