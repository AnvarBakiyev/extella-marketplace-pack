# expert: validator_js_validate
# description: Inspired by validator.js — the most popular string validation library on GitHub.

def validator_js_validate(value='', rule='email'):
    import re, json
    p = {'email': r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$', 'url': r'^https?://[^\s]+$', 'ipv4': r'^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$'}
    try:
        valid = bool(re.match(p.get(rule,''), value.strip())) if rule in p else False
        return json.dumps({'status':'success','output_type':'json','data':{'valid':valid}})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
