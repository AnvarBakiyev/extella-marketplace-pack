# expert: marked_md_to_html
# description: Inspired by marked — the fastest Markdown parser on GitHub with 30k+ stars. Converts GitHub-flavored Markdown to clean HTML.

def marked_md_to_html(markdown=''):
    import re, json
    try:
        h = markdown
        h = re.sub(r'^###### (.+)$', r'<h6>\1</h6>', h, flags=re.M)
        h = re.sub(r'^##### (.+)$', r'<h5>\1</h5>', h, flags=re.M)
        h = re.sub(r'^#### (.+)$', r'<h4>\1</h4>', h, flags=re.M)
        h = re.sub(r'^### (.+)$', r'<h3>\1</h3>', h, flags=re.M)
        h = re.sub(r'^## (.+)$', r'<h2>\1</h2>', h, flags=re.M)
        h = re.sub(r'^# (.+)$', r'<h1>\1</h1>', h, flags=re.M)
        h = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', h)
        h = re.sub(r'\*(.+?)\*', r'<em>\1</em>', h)
        h = re.sub(r'`([^`]+)`', r'<code>\1</code>', h)
        h = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', h)
        h = re.sub(r'\n\n', '</p><p>', h)
        return json.dumps({'status':'success','output_type':'text','data':'<p>'+h+'</p>'})
    except Exception as e: return json.dumps({'status':'error','message':str(e)})
