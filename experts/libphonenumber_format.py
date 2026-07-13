# expert: libphonenumber_format
# description: Inspired by Google libphonenumber.

def libphonenumber_format(phone='', country=''):
    import re, json
    try: d=re.sub(r'\D','',phone); e164='+'+d if phone.strip().startswith('+') else '+1'+d[-10:]; return json.dumps({'status':'success','output_type':'json','data':{'e164':e164}})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
