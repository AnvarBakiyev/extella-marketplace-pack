# expert: open_graph_extract
# description: Inspired by Open Graph protocol — extract og:title, og:image, og:description and Twitter Card meta tags from any webpage HTML.

def open_graph_extract(html=''):
    import re, json
    try:
        og = re.findall(r'<meta[^>]+property=["\']og:([^"\']+)["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
        og += re.findall(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:([^"\']+)["\']', html, re.I)
        tw = re.findall(r'<meta[^>]+name=["\']twitter:([^"\']+)["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
        tags = {('og:'+k if not k.startswith('og:') else k): v for k,v in og}
        tags.update({'twitter:'+k: v for k,v in tw})
        return json.dumps({'status':'success','output_type':'json','data':tags})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
