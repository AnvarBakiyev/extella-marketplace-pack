# expert: lodash_get_value
# description: Inspired by lodash.get — safely access deeply nested properties without TypeError on undefined paths.

def lodash_get_value(json_text='', path=''):
    import json
    try:
        data = json.loads(json_text); cur = data
        for part in path.replace('[', '.').replace(']', '').split('.'):
            if not part: continue
            if isinstance(cur, dict): cur = cur.get(part)
            elif isinstance(cur, list) and part.isdigit(): cur = cur[int(part)]
            else: cur = None; break
        return json.dumps({'status':'success','output_type':'json','data':{'path':path,'value':cur}})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
