# expert: slugify_make
# description: Inspired by slugify.

def slugify_make(text='', separator='-'):
    import re, json, unicodedata
    try: s=unicodedata.normalize('NFKD',text).encode('ascii','ignore').decode(); s=re.sub(r'[^\w\s-]','',s.lower()); s=re.sub(r'[-\s]+',separator,s).strip(separator); return json.dumps({'status':'success','output_type':'text','data':s})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
