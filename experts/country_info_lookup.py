# expert: country_info_lookup
# description: Returns facts about a country: official name, capital, population, region, languages, currencies, flag, and more. Uses restcountries.com. Param: query (country name or 2/3-letter code). Returns JSON w

def country_info_lookup(query='Germany'):
    import urllib.request, urllib.parse, json
    try:
        q = query.strip()
        if len(q) <= 3 and q.isalpha():
            url = 'https://restcountries.com/v3.1/alpha/' + urllib.parse.quote(q)
        else:
            url = 'https://restcountries.com/v3.1/name/' + urllib.parse.quote(q) + '?fullText=false'
        req = urllib.request.Request(url, headers={'User-Agent': 'ExtellaTool/1.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        if isinstance(data, list): c = data[0]
        else: c = data
        langs = list(c.get('languages', {}).values())[:5]
        currs = [v.get('name', k) for k, v in c.get('currencies', {}).items()][:3]
        result = {'name': c.get('name', {}).get('common', q), 'official_name': c.get('name', {}).get('official', ''), 'capital': (c.get('capital') or [''])[0], 'population': c.get('population', 0), 'area_km2': c.get('area', 0), 'region': c.get('region', ''), 'subregion': c.get('subregion', ''), 'languages': langs, 'currencies': currs, 'flag': c.get('flag', ''), 'calling_code': '+' + (c.get('idd', {}).get('root', '') + (c.get('idd', {}).get('suffixes') or [''])[0]).lstrip('+'), 'timezone': (c.get('timezones') or [''])[0]}
        return json.dumps({'status': 'success', 'output_type': 'json', 'data': result})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
