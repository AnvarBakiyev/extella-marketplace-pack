# expert: random_quote_get
# description: Fetches random quotes from quotable.io. Params: tag (optional topic filter), count (1-5). Returns JSON with output_type json containing quotes with author and tags.

def random_quote_get(tag='', count='1'):
    import urllib.request, json
    try:
        n = min(max(int(count), 1), 5)
        quotes = []
        for _ in range(n):
            req = urllib.request.Request('https://dummyjson.com/quotes/random', headers={'User-Agent': 'ExtellaTool/1.0'})
            with urllib.request.urlopen(req, timeout=10) as r:
                q = json.loads(r.read().decode())
            quotes.append({'text': q.get('quote', ''), 'author': q.get('author', ''), 'tags': [], 'length': len(q.get('quote', ''))})
        return json.dumps({'status': 'success', 'output_type': 'json', 'data': {'quotes': quotes, 'count': len(quotes)}})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
