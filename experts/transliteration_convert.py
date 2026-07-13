# expert: transliteration_convert
# description: Inspired by transliteration libraries.

def transliteration_convert(text=''):
    import json, unicodedata
    try: return json.dumps({'status':'success','output_type':'text','data':unicodedata.normalize('NFKD',text).encode('ascii','ignore').decode()})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
