# expert: svc_currency
# description: Сервис: актуальный курс валют (USD, EUR, KZT, RUB и др.) и конвертация суммы. Источник exchangerate-api. Параметры: base, to, amount.

def svc_currency(base="USD", to="KZT", amount="1") -> str:
    import json, urllib.request, ssl
    base = "USD" if (not base or str(base).startswith("{{")) else str(base).upper().strip()
    to   = "KZT" if (not to or str(to).startswith("{{")) else str(to).upper().strip()
    amount = "1" if (not amount or str(amount).startswith("{{")) else str(amount)
    try: amt=float(amount.replace(",",".").replace(" ",""))
    except Exception: amt=1.0
    try:
        ctx=ssl.create_default_context()
        u="https://open.er-api.com/v6/latest/"+base
        d=json.loads(urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"ExtellaSvc/1.0"}),timeout=20,context=ctx).read())
        rate=d.get("rates",{}).get(to)
        if not rate: return json.dumps({"status":"error","message":"нет курса "+base+" \u2192 "+to}, ensure_ascii=False)
        return json.dumps({"status":"success","base":base,"to":to,"rate":rate,"amount":amt,"converted":round(amt*rate,2),"updated":d.get("time_last_update_utc","")[:16]}, ensure_ascii=False)
    except Exception as e: return json.dumps({"status":"error","message":str(e)[:120]}, ensure_ascii=False)