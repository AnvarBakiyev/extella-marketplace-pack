# expert: dotenv_parser_parse
# description: Inspired by dotenv — the most popular environment variable loader with 18k+ GitHub stars. Parses .env file contents into structured variables.

def dotenv_parser_parse(env_text=''):
    import json, re
    try:
        result = {}
        for line in env_text.splitlines():
            line = line.strip()
            if not line or line.startswith('#'): continue
            if '=' in line:
                k, v = line.split('=', 1); v = v.strip().strip('"').strip("'")
                result[k.strip()] = v
        return json.dumps({'status':'success','output_type':'json','data':result})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
