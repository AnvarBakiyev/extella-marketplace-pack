# expert: svc_qr
# description: Сервис: генерирует QR-код по тексту/ссылке (возвращает ссылку на картинку PNG). Параметр: data.

def svc_qr(data="https://extella.ai") -> str:
    import json, urllib.request, urllib.parse, ssl
    data = "https://extella.ai" if (not data or str(data).startswith("{{")) else str(data)
    try:
        url="https://api.qrserver.com/v1/create-qr-code/?"+urllib.parse.urlencode({"size":"300x300","data":data})
        ctx=ssl.create_default_context()
        code=urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"ExtellaSvc/1.0"}),timeout=20,context=ctx).getcode()
        if code!=200: return json.dumps({"status":"error","message":"генератор недоступен"}, ensure_ascii=False)
        return json.dumps({"status":"success","data":data,"image_url":url}, ensure_ascii=False)
    except Exception as e: return json.dumps({"status":"error","message":str(e)[:120]}, ensure_ascii=False)