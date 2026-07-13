# expert: base64_codec_convert
# description: Encodes plain text to Base64 or decodes a Base64 string back to text. Params: text (input string, required), operation (encode or decode, default encode). Returns JSON with output_type text.

def base64_codec_convert(text='', operation='encode'):
    import base64, json
    try:
        if operation == 'encode':
            result = base64.b64encode(text.encode('utf-8')).decode('utf-8')
        else:
            result = base64.b64decode(text.encode('utf-8')).decode('utf-8')
        return json.dumps({'status': 'success', 'output_type': 'text', 'data': result})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
