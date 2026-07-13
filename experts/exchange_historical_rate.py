# expert: exchange_historical_rate
# description: Official NB Kazakhstan exchange rate for a given date (KZT pairs, cross-rates supported); ECB fallback for non-KZT pairs.

def exchange_historical_rate(date='', from_currency='USD', to_currency='KZT'):
    import urllib.request, json, re
    try:
        frm, to = from_currency.upper().strip(), to_currency.upper().strip()
        d = date.strip()
        m = re.match(r'^(\d{4})-(\d{2})-(\d{2})$', d)
        fdate = (m.group(3)+'.'+m.group(2)+'.'+m.group(1)) if m else d  # НБ РК ждёт ДД.ММ.ГГГГ
        # 1) Официальный курс Нацбанка РК на дату (все пары через тенге)
        url = 'https://nationalbank.kz/rss/get_rates.cfm?fdate='+fdate
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
            return json.dumps({'status':'success','output_type':'json','data':{'date':fdate,'from':frm,'to':to,'rate':round(rate,6),'source':'Нацбанк РК, официальный курс'}}, ensure_ascii=False)
        # 2) Запасной источник: европейский ЦБ (пары без тенге и рубля)
        url2 = 'https://api.frankfurter.app/'+d+'?from='+frm+'&to='+to
        req2 = urllib.request.Request(url2, headers={'User-Agent':'ExtellaTool/1.0'})
        with urllib.request.urlopen(req2, timeout=10) as r: data = json.loads(r.read().decode())
        return json.dumps({'status':'success','output_type':'json','data':{'date':data.get('date'),'from':frm,'to':to,'rate':data['rates'].get(to),'source':'Европейский ЦБ'}}, ensure_ascii=False)
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
