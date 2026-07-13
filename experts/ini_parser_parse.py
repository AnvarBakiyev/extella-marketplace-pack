# expert: ini_parser_parse
# description: Inspired by the npm ini module — parse .ini configuration files into structured key-value sections.

def ini_parser_parse(ini_text=''):
    import configparser, json, io
    try:
        text = ini_text.strip()
        if text and not any(line.strip().startswith('[') for line in text.splitlines()):
            text = '[DEFAULT]\n' + text
        cp = configparser.ConfigParser(); cp.read_file(io.StringIO(text))
        result = {s: dict(cp.items(s)) for s in cp.sections()}
        if not result and cp.defaults():
            result = {'DEFAULT': dict(cp.defaults())}
        return json.dumps({'status':'success','output_type':'json','data':result})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
