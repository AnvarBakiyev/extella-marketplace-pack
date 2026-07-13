# expert: franc_detect
# description: Inspired by franc.

def franc_detect(text=''):
    import re, json
    try:
        t = text.lower()
        if re.search(r'[а-яё]', t): lang = 'Russian'
        elif re.search(r'[\u4e00-\u9fff]', text): lang = 'Chinese'
        elif re.search(r'[\u0600-\u06ff]', text): lang = 'Arabic'
        elif re.search(r'[àâäéèê]', t): lang = 'French/German'
        else: lang = 'English (likely)'
        return json.dumps({'status':'success','output_type':'json','data':{'language':lang}})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
