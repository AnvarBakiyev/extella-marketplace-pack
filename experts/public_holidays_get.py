# expert: public_holidays_get
# description: Returns official public holidays for a country and year using date.nager.at. Params: country_code (2-letter ISO code like US/DE/FR), year (4-digit year, defaults to current year). Returns JSON with ou

def public_holidays_get(country_code='US', year=''):
    import urllib.request, json, datetime
    try:
        cc = country_code.upper().strip()[:2]
        yr = year.strip() if year.strip() else str(datetime.date.today().year)
        url = 'https://date.nager.at/api/v3/PublicHolidays/' + yr + '/' + cc
        req = urllib.request.Request(url, headers={'User-Agent': 'ExtellaTool/1.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        holidays = [{'date': h.get('date'), 'name': h.get('localName', h.get('name', '')), 'name_en': h.get('name', ''), 'type': ', '.join(h.get('types', ['Public']))} for h in data]
        result = {'country': cc, 'year': yr, 'count': len(holidays), 'holidays': holidays}
        return json.dumps({'status': 'success', 'output_type': 'json', 'data': result})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
