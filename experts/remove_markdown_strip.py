# expert: remove_markdown_strip
# description: Inspired by remove-markdown.

def remove_markdown_strip(markdown=''):
    import re, json
    try: t=re.sub(r'```[\s\S]*?```','',markdown); t=re.sub(r'`([^`]+)`',r'\1',t); t=re.sub(r'\[([^\]]+)\]\([^)]+\)',r'\1',t); t=re.sub(r'^#{1,6}\s+','',t,flags=re.M); return json.dumps({'status':'success','output_type':'text','data':t.strip()})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
