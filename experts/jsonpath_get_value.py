# expert: jsonpath_get_value
# description: Inspired by JSONPath — query JSON documents with dot-notation paths like $.store.book[0].title.

def jsonpath_get_value(json_text='', path=''):
    import json
    try:
        data = json.loads(json_text)
        cur = data
        for part in path.replace('[', '.').replace(']', '').split('.'):
            if not part: continue
            if isinstance(cur, dict): cur = cur.get(part)
            elif isinstance(cur, list): cur = cur[int(part)]
            else: cur = None
        return json.dumps({'status':'success','output_type':'json','data':{'path':path,'value':cur}})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
