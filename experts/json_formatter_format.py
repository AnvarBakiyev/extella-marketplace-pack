# expert: json_formatter_format
# description: Formats or minifies JSON text. Params: json_text (raw JSON string), operation (prettify/minify), indent (indent spaces, default 2). Returns JSON with output_type text containing formatted/minified JSO

def json_formatter_format(json_text='{}', operation='prettify', indent='2'):
    import json
    try:
        parsed = json.loads(json_text)
        if operation == 'minify':
            result = json.dumps(parsed, separators=(',', ':'), ensure_ascii=False)
        else:
            result = json.dumps(parsed, indent=int(indent), ensure_ascii=False)
        return json.dumps({'status': 'success', 'output_type': 'text', 'data': result})
    except json.JSONDecodeError as e:
        return json.dumps({'status': 'error', 'message': 'Invalid JSON: ' + str(e)})
    except Exception as e:
        return json.dumps({'status': 'error', 'message': str(e)})
