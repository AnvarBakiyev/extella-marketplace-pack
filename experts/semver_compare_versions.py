# expert: semver_compare_versions
# description: Inspired by node-semver — the npm semver library used by every package manager. Compare, sort, and validate semantic version strings.

def semver_compare_versions(v1='', v2=''):
    import json, re
    def parse(v):
        m = re.match(r'(\d+)\.(\d+)\.(\d+)', v.strip())
        return tuple(int(x) for x in m.groups()) if m else (0,0,0)
    try:
        a, b = parse(v1), parse(v2)
        cmp = 'equal' if a==b else ('greater' if a>b else 'less')
        return json.dumps({'status':'success','output_type':'json','data':{'v1':v1,'v2':v2,'comparison':cmp}})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
