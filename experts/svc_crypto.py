# expert: svc_crypto
# description: Сервис: курс криптовалюты (bitcoin, ethereum, the-open-network, solana и др.) в usd/kzt/rub. Источник CoinGecko. Параметры: coin, vs.

def svc_crypto(coin="bitcoin", vs="usd") -> str:
    import json, urllib.request, ssl
    coin = "bitcoin" if (not coin or str(coin).startswith("{{")) else str(coin).lower().strip()
    vs   = "usd" if (not vs or str(vs).startswith("{{")) else str(vs).lower().strip()
    try:
        ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
        u="https://api.coingecko.com/api/v3/simple/price?ids="+coin+"&vs_currencies="+vs
        d=json.loads(urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"ExtellaSvc/1.0"}),timeout=20,context=ctx).read())
        if coin not in d or vs not in d.get(coin,{}): return json.dumps({"status":"error","message":"не найдена монета/валюта: "+coin+"/"+vs}, ensure_ascii=False)
        return json.dumps({"status":"success","coin":coin,"vs":vs,"price":d[coin][vs]}, ensure_ascii=False)
    except Exception as e: return json.dumps({"status":"error","message":str(e)[:120]}, ensure_ascii=False)