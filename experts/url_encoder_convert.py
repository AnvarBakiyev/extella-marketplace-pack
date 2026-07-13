# expert: url_encoder_convert
# description: Percent-encodes or decodes URL strings. Params: text (input string), operation (encode/decode), mode (component encodes everything except unreserved chars; full preserves URL structure). Returns JSON 

def url_encoder_convert(text='', operation='encode', mode='component'):
    import urllib.parse, json
    try:
        if operation == 'encode':
            if mode == 'full':
                result = urllib.parse.quote(text, safe=':/?#[]@!$&\'()*+,;=')
            else:
                result = urllib.parse.quote(text, safe='')
        else:
            result = urllib.parse.unquote(text)
        return json.dumps({'status': 'success', 'output_type': 'text', 'data': result})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
