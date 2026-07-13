# expert: jsbarcode_generate
# description: Inspired by JsBarcode.

def jsbarcode_generate(text='', format='code128'):
    import urllib.parse, json
    try: bc='ean13' if format=='ean13' else 'code128'; url='https://bwipjs-api.metafloor.com/?bcid='+bc+'&text='+urllib.parse.quote(text); return json.dumps({'status':'success','output_type':'text','data':url})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
