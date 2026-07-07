# expert: svc_ipgeo
# description: Сервис: геолокация по IP-адресу (страна, город, провайдер). Источник ip-api. Параметр: ip.

def svc_ipgeo(ip="8.8.8.8") -> str:
    import json, urllib.request, ssl
    ip = "8.8.8.8" if (not ip or str(ip).startswith("{{")) else str(ip).strip()
    try:
        ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
        d=json.loads(urllib.request.urlopen(urllib.request.Request("http://ip-api.com/json/"+ip+"?lang=ru",headers={"User-Agent":"ExtellaSvc/1.0"}),timeout=20,context=ctx).read())
        if d.get("status")!="success": return json.dumps({"status":"error","message":"не удалось определить: "+ip}, ensure_ascii=False)
        return json.dumps({"status":"success","ip":ip,"country":d.get("country"),"city":d.get("city"),"region":d.get("regionName"),"isp":d.get("isp")}, ensure_ascii=False)
    except Exception as e: return json.dumps({"status":"error","message":str(e)[:120]}, ensure_ascii=False)