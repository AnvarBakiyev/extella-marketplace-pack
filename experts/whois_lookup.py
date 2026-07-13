# expert: whois_lookup
# description: Uses RDAP/WHOIS — look up domain registration, expiry, and status.

def whois_lookup(domain=''):
    import urllib.request, json
    try:
        d = domain.strip().replace('https://','').replace('http://','').split('/')[0]
        url = 'https://rdap.org/domain/'+d
        req = urllib.request.Request(url, headers={'User-Agent': 'ExtellaTool/1.0'})
        with urllib.request.urlopen(req, timeout=10) as r: data = json.loads(r.read().decode())
        events = {e.get('eventAction',''): e.get('eventDate','')[:10] for e in data.get('events',[])}
        return json.dumps({'status':'success','output_type':'json','data':{'domain':d,'handle':data.get('handle',''),'status':data.get('status',[]),'registered':events.get('registration',''),'expires':events.get('expiration','')}})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
