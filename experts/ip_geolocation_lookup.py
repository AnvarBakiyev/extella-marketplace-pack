# expert: ip_geolocation_lookup
# description: Returns geolocation and network info for an IP address using ip-api.com. Param: ip (IPv4/IPv6 string, or blank for caller's IP). Returns JSON with output_type json containing country, city, ISP, timez

def ip_geolocation_lookup(ip=''):
    import urllib.request, json
    try:
        target = ip.strip() if ip.strip() else ''
        url = 'http://ip-api.com/json/' + target + '?fields=status,message,country,countryCode,region,regionName,city,zip,lat,lon,timezone,isp,org,as,query'
        req = urllib.request.Request(url, headers={'User-Agent': 'ExtellaTool/1.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        if data.get('status') == 'fail':
            return json.dumps({'status': 'error', 'message': data.get('message', 'Lookup failed')})
        result = {'ip': data.get('query'), 'country': data.get('country'), 'country_code': data.get('countryCode'), 'region': data.get('regionName'), 'city': data.get('city'), 'zip': data.get('zip'), 'timezone': data.get('timezone'), 'isp': data.get('isp'), 'org': data.get('org'), 'coordinates': {'lat': data.get('lat'), 'lon': data.get('lon')}}
        return json.dumps({'status': 'success', 'output_type': 'json', 'data': result})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
