# expert: cheerio_extract
# description: Inspired by Cheerio — fast, flexible jQuery-like HTML parsing for Node.js with 28k+ stars. Extract links, text, and meta tags from any HTML.

def cheerio_extract(html='', mode='links'):
    import re, json
    try:
        if mode == 'links':
            links = re.findall(r'href=["\']([^"\']+)["\']', html)
            data = {'links': links[:50], 'count': len(links)}
        elif mode == 'title':
            title = re.search(r'<title[^>]*>([^<]+)</title>', html, re.I)
            og = re.findall(r'property=["\']og:([^"\']+)["\'][^>]*content=["\']([^"\']+)["\']', html)
            data = {'title': title.group(1).strip() if title else '', 'og_tags': dict(og[:10])}
        else:
            text = re.sub(r'<[^>]+>', ' ', html); text = re.sub(r'\s+', ' ', text).strip()
            data = {'text': text[:2000], 'length': len(text)}
        return json.dumps({'status':'success','output_type':'json','data':data})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
