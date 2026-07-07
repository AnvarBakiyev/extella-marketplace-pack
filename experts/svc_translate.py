# expert: svc_translate
# description: Сервис: перевод короткого текста между языками. Источник MyMemory. Параметры: text, src (en/ru/kk...), to.

def svc_translate(text="hello", src="en", to="ru") -> str:
    import json, urllib.request, urllib.parse, ssl
    text = "hello" if (not text or str(text).startswith("{{")) else str(text)
    src = "en" if (not src or str(src).startswith("{{")) else str(src).lower().strip()
    to  = "ru" if (not to or str(to).startswith("{{")) else str(to).lower().strip()
    try:
        ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
        u="https://api.mymemory.translated.net/get?"+urllib.parse.urlencode({"q":text[:400],"langpair":src+"|"+to})
        d=json.loads(urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"ExtellaSvc/1.0"}),timeout=20,context=ctx).read())
        tr=d.get("responseData",{}).get("translatedText")
        if not tr: return json.dumps({"status":"error","message":"перевод не получен"}, ensure_ascii=False)
        return json.dumps({"status":"success","src":src,"to":to,"original":text,"translated":tr}, ensure_ascii=False)
    except Exception as e: return json.dumps({"status":"error","message":str(e)[:120]}, ensure_ascii=False)