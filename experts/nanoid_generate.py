# expert: nanoid_generate
# description: Inspired by Nano ID — used in millions of JS projects.

def nanoid_generate(size='21', alphabet='url'):
    import secrets, json
    a={'url':'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-','alnum':'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789','hex':'0123456789abcdef'}
    try: c=a.get(alphabet,a['url']); n=min(max(int(size),4),64); return json.dumps({'status':'success','output_type':'text','data':''.join(secrets.choice(c) for _ in range(n))})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
