# expert: currency_converter_convert
# description: Currency conversion via National Bank of Kazakhstan official rates (KZT pairs); open.er-api.com fallback for other pairs.

def currency_converter_convert(amount='100', from_currency='USD', to_currency='KZT'):
    import urllib.request, json, re
    try:
        frm, to = from_currency.upper().strip(), to_currency.upper().strip()
        amt = float(str(amount).replace(',', '.').replace(' ', ''))
        # 1) Свежие официальные курсы Нацбанка РК (все пары через тенге)
        import time; url = 'https://nationalbank.kz/rss/get_rates.cfm?fdate='+time.strftime('%d.%m.%Y')
        req = urllib.request.Request(url, headers={'User-Agent':'ExtellaTool/1.0'})
        with urllib.request.urlopen(req, timeout=15) as r: xml = r.read().decode('utf-8','ignore')
        rates = {'KZT': 1.0}
        for it in re.findall(r'<item>(.*?)</item>', xml, re.S):
            t = re.search(r'<title>\s*([A-Z]{3})\s*</title>', it)
            de = re.search(r'<description>\s*([\d.,]+)\s*</description>', it)
            q = re.search(r'<quant>\s*(\d+)\s*</quant>', it)
            if t and de:
                rates[t.group(1)] = float(de.group(1).replace(',','.'))/float(q.group(1) if q else 1)
        if len(rates) > 1 and frm in rates and to in rates:
            rate = rates[frm]/rates[to]
            return json.dumps({'status':'success','output_type':'json','data':{'amount':amt,'from':frm,'to':to,'rate':round(rate,6),'converted':round(amt*rate,2),'source':'Нацбанк РК'}}, ensure_ascii=False)
        # 2) Запасной: открытый курс (пары без тенге)
        url2 = 'https://open.er-api.com/v6/latest/'+frm
        req2 = urllib.request.Request(url2, headers={'User-Agent':'ExtellaTool/1.0'})
        with urllib.request.urlopen(req2, timeout=10) as r: data = json.loads(r.read().decode())
        rate = (data.get('rates') or {}).get(to)
        if rate is None: return json.dumps({'status':'error','message':'Валюта не найдена: '+to})
        return json.dumps({'status':'success','output_type':'json','data':{'amount':amt,'from':frm,'to':to,'rate':rate,'converted':round(amt*rate,2),'source':'open.er-api.com'}}, ensure_ascii=False)
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
