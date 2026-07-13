# expert: toml_parser_parse
# description: Inspired by TOML — parse TOML configuration files (used by Cargo, pyproject.toml, Hugo) into JSON.

def toml_parser_parse(toml_text=''):
    import json
    try:
        try: import tomllib
        except ImportError: import tomli as tomllib
        data = tomllib.loads(toml_text)
        return json.dumps({'status':'success','output_type':'text','data':json.dumps(data, indent=2, default=str)})
    except Exception as e:
        try:
            result = {}; section = None
            for line in toml_text.splitlines():
                line = line.strip()
                if not line or line.startswith('#'): continue
                if line.startswith('[') and line.endswith(']'):
                    section = line[1:-1]; result[section] = {}; continue
                if '=' in line:
                    k, v = line.split('=', 1); k = k.strip(); v = v.strip().strip('"')
                    if section: result[section][k] = v
                    else: result[k] = v
            return json.dumps({'status':'success','output_type':'text','data':json.dumps(result, indent=2)})
        except Exception as e2: return json.dumps({'status':'error','message':str(e2)})
