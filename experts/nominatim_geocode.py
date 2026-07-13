# expert: nominatim_geocode
# description: Uses OpenStreetMap Nominatim — the free geocoding service behind millions of map applications worldwide.

def nominatim_geocode(query=''):
    import urllib.request, urllib.parse, json
    try:
        url = 'https://nominatim.openstreetmap.org/search?q='+urllib.parse.quote(query)+'&format=json&limit=3'
        req = urllib.request.Request(url, headers={'User-Agent': 'ExtellaTool/1.0'})
        with urllib.request.urlopen(req, timeout=10) as r: data = json.loads(r.read().decode())
        results = [{'name':d.get('display_name'),'lat':d.get('lat'),'lon':d.get('lon'),'type':d.get('type')} for d in data[:3]]
        return json.dumps({'status':'success','output_type':'json','data':{'results':results,'count':len(results)}})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
